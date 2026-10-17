"""LoopCloser API (FastAPI on Cloud Run).

Care-continuity system, not a diagnostic AI. Deterministic rules decide; humans
review, escalate and close; Gemini only drafts text.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth
from .ai.assist import summarize_case
from .auth import Principal, require
from .config import Config, get_config
from .domain import commands as cmd
from .domain.case import CaseView
from .domain.errors import DomainError
from .domain.events import SYSTEM_ACTOR
from .domain.roles import Perm, has_perm
from .domain.states import CaseState
from .imports.csv_validation import validate_csv
from .logging_setup import request_id_var, setup_logging, trace_var
from .pathways.library import PathwayLibrary, default_library
from .ratelimit import SlidingWindowLimiter
from .store.base import CaseRepository
from .synth.generator import DISCLAIMER, LABEL, generate

log = logging.getLogger("loopcloser")
SENSITIVE_PREFIXES = ("/api/imports", "/api/ai", "/api/demo")
MAX_CSV_BYTES = 5 * 1024 * 1024


def mask_participant(pid: str) -> str:
    return f"P-••••{pid[-2:]}" if len(pid) >= 2 else "P-••••"


def _make_repo(cfg: Config) -> CaseRepository:
    if cfg.storage_backend == "firestore":
        from .store.firestore import FirestoreRepository

        return FirestoreRepository()
    from .store.memory import MemoryRepository

    return MemoryRepository()


# ------------------------------------------------------------------ request models


class OpenCaseIn(BaseModel):
    case_id: str | None = None
    participant_id: str
    screening_id: str
    screening_type: str
    result: str
    severity: str
    screened_at: date
    red_flag: bool = False
    owner: str | None = None


class AssignIn(BaseModel):
    owner: str | None = None
    backup_owner: str | None = None
    clinician_reviewer: str | None = None


class TransitionIn(BaseModel):
    target: CaseState
    reason: str | None = None
    escalation_date: date | None = None
    source: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class ContactIn(BaseModel):
    channel: str
    result: str


class NotificationIn(BaseModel):
    status: str
    channel: str = "sms"
    template_id: str
    template_version: str
    language: str = "en"


class RedFlagIn(BaseModel):
    source: str = "staff"
    code: str = "new_symptoms"


class ResumeIn(BaseModel):
    reason: str


class CloseIn(BaseModel):
    closure_reason: str
    evidence_ref: str | None = None
    sign_off: bool = False


class NoteIn(BaseModel):
    text: str = Field(max_length=2000)


# ------------------------------------------------------------------ app factory


def create_app(
    cfg: Config | None = None, repo: CaseRepository | None = None, library: PathwayLibrary | None = None
) -> FastAPI:
    cfg = cfg or get_config()
    setup_logging()
    repo = repo or _make_repo(cfg)
    lib = library or default_library()
    general = SlidingWindowLimiter(cfg.rate_limit_per_minute)
    sensitive = SlidingWindowLimiter(cfg.rate_limit_sensitive_per_minute)
    settings = cmd.Settings(escalate_after_failed_contacts=cfg.escalate_after_failed_contacts)

    app = FastAPI(
        title="LoopCloser API", version=cfg.version, docs_url=None if cfg.is_production else "/docs", redoc_url=None
    )
    app.state.repo, app.state.cfg, app.state.lib = repo, cfg, lib

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["authorization", "content-type", "x-demo-role", "x-demo-user"],
    )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        tc = request.headers.get("x-cloud-trace-context", "")
        trace_var.set(tc.split("/")[0] if tc else None)
        path = request.url.path
        if path.startswith("/api/"):
            fwd = request.headers.get("x-forwarded-for", "")
            ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
            limiter = sensitive if path.startswith(SENSITIVE_PREFIXES) else general
            ok, retry = limiter.check(f"{ip}:{'s' if limiter is sensitive else 'g'}")
            if not ok:
                log.warning("rate limited", extra={"fields": {"path": path, "request_id": rid}})
                return JSONResponse(
                    {"detail": "Too many requests. Please slow down.", "request_id": rid},
                    status_code=429,
                    headers={"Retry-After": str(retry), "X-Request-Id": rid},
                )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"fields": {"path": path}})
            response = JSONResponse(
                {"detail": "Internal error. Quote this id when reporting it.", "request_id": rid}, status_code=500
            )
        ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-Id"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        log.info(
            "request",
            extra={
                "fields": {
                    "httpRequest": {
                        "requestMethod": request.method,
                        "requestUrl": path,
                        "status": response.status_code,
                        "latency": f"{ms / 1000:.3f}s",
                    }
                }
            },
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return JSONResponse(
            {"detail": exc.message, "rule_id": exc.rule_id, "request_id": request_id_var.get()},
            status_code=exc.status_code,
        )

    # -------------------------------------------------------------- health

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Liveness. Cheap, no dependencies. (Cloud Run reserves paths ending in 'z'.)"""
        return {"status": "ok", "version": cfg.version, "time": datetime.now(UTC).isoformat()}

    @app.get("/ready")
    def ready() -> JSONResponse:
        checks: dict[str, Any] = {}
        try:
            checks["storage"] = cfg.storage_backend if repo.ping() else "down"
        except Exception:  # noqa: BLE001
            log.exception("readiness: storage check failed")
            checks["storage"] = "down"
        problems = lib.lock_mismatches()
        checks["pathways"] = len(lib.latest()) if not problems else "lock mismatch"
        checks["auth_mode"] = cfg.auth_mode
        checks["ai"] = "gemini" if cfg.gemini_api_key else "mock"
        ok = checks["storage"] != "down" and not problems
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503
        )

    # -------------------------------------------------------------- identity

    @app.get("/api/me")
    def me(p: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        from .domain.roles import PERMISSIONS

        return {
            "uid": p.uid,
            "role": p.role.value,
            "demo": p.demo,
            "permissions": sorted(x.value for x in PERMISSIONS[p.role]),
        }

    # -------------------------------------------------------------- pathways

    @app.get("/api/pathways")
    def pathways(_: Principal = Depends(require(Perm.PATHWAY_READ))) -> list[dict]:
        return [p.model_dump() for p in lib.latest()]

    # -------------------------------------------------------------- cases

    def _out(v: CaseView, p: Principal) -> dict[str, Any]:
        d = v.to_doc()
        if p.role.value != "patient":
            d["participant_id"] = mask_participant(v.participant_id)
        d.pop("patient_uid", None)
        return d

    def _visible(v: CaseView, p: Principal) -> bool:
        if has_perm(p.role, Perm.CASE_READ_ALL):
            return True
        if has_perm(p.role, Perm.CASE_READ_ASSIGNED):
            return p.uid in {v.owner, v.backup_owner}
        if has_perm(p.role, Perm.CASE_READ_OWN):
            return bool(v.patient_uid) and v.patient_uid == p.uid
        return False

    def _get_visible(case_id: str, p: Principal) -> CaseView:
        v = repo.get_case(case_id)
        if not v or not _visible(v, p):
            raise HTTPException(404, "Case not found.")  # same answer for hidden and missing
        return v

    @app.get("/api/cases")
    def list_cases(
        p: Principal = Depends(auth.current_user), state: CaseState | None = None, limit: int = Query(200, le=1000)
    ) -> dict[str, Any]:
        rows = [v for v in repo.list_cases() if _visible(v, p) and (state is None or v.state == state)]
        rows.sort(key=lambda v: (v.state == CaseState.CLOSED, v.due_date or date.max, v.id))
        return {"total": len(rows), "cases": [_out(v, p) for v in rows[:limit]]}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, p: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        return _out(_get_visible(case_id, p), p)

    @app.get("/api/cases/{case_id}/events")
    def case_events(case_id: str, p: Principal = Depends(require(Perm.EVENTS_READ))) -> list[dict]:
        _get_visible(case_id, p)
        return [e.to_doc() for e in repo.load_events(case_id)]

    @app.post("/api/cases", status_code=201)
    def open_case(body: OpenCaseIn, p: Principal = Depends(require(Perm.CASE_OPEN))) -> dict[str, Any]:
        pw = lib.match(body.screening_type, body.result, body.severity)
        if not pw:
            raise HTTPException(422, "No pathway matches this result. It needs human review.")
        case_id = body.case_id or f"C-{uuid.uuid4().hex[:10]}"
        v = cmd.open_case(
            repo, case_id=case_id, screening=body.model_dump(mode="json"), pathway=pw, actor=p.actor, owner=body.owner
        )
        return _out(v, p)

    @app.post("/api/cases/{case_id}/assign")
    def assign(case_id: str, body: AssignIn, p: Principal = Depends(require(Perm.CASE_ASSIGN))):
        _get_visible(case_id, p)
        return _out(cmd.assign(repo, case_id, actor=p.actor, **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/transition")
    def transition(case_id: str, body: TransitionIn, p: Principal = Depends(require(Perm.CASE_TRANSITION))):
        _get_visible(case_id, p)
        if body.target in {CaseState.RESOLVED_BY_HUMAN, CaseState.CLINICIAN_CONTACTED} and not has_perm(
            p.role, Perm.RED_FLAG_RESOLVE
        ):
            raise HTTPException(403, "Your role cannot resolve red flags.")
        payload = body.model_dump(mode="json", exclude={"target"}, exclude_none=True)
        return _out(cmd.transition(repo, case_id, body.target, actor=p.actor, payload=payload), p)

    @app.post("/api/cases/{case_id}/contact-attempts")
    def contact(case_id: str, body: ContactIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        _get_visible(case_id, p)
        return _out(
            cmd.log_contact_attempt(
                repo, case_id, channel=body.channel, result=body.result, actor=p.actor, settings=settings
            ),
            p,
        )

    @app.post("/api/cases/{case_id}/notifications")
    def notification(case_id: str, body: NotificationIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        """Simulated outbox status. No real SMS is sent."""
        _get_visible(case_id, p)
        return _out(cmd.record_notification(repo, case_id, actor=p.actor, **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/red-flag")
    def red_flag(case_id: str, body: RedFlagIn, p: Principal = Depends(require(Perm.RED_FLAG_REPORT))):
        _get_visible(case_id, p)
        source = "patient" if p.role.value == "patient" else body.source
        return _out(cmd.report_red_flag(repo, case_id, actor=p.actor, source=source, code=body.code), p)

    @app.post("/api/cases/{case_id}/resume-automation")
    def resume(case_id: str, body: ResumeIn, p: Principal = Depends(require(Perm.AUTOMATION_RESUME))):
        _get_visible(case_id, p)
        return _out(cmd.resume_automation(repo, case_id, actor=p.actor, reason=body.reason), p)

    @app.post("/api/cases/{case_id}/close")
    def close(case_id: str, body: CloseIn, p: Principal = Depends(require(Perm.CASE_CLOSE))):
        _get_visible(case_id, p)
        return _out(cmd.close_case(repo, case_id, actor=p.actor, **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/notes")
    def note(case_id: str, body: NoteIn, p: Principal = Depends(require(Perm.CASE_NOTE))):
        _get_visible(case_id, p)
        return _out(cmd.add_note(repo, case_id, actor=p.actor, text=body.text), p)

    @app.post("/api/ai/cases/{case_id}/summary")
    def ai_summary(case_id: str, p: Principal = Depends(require(Perm.CASE_NOTE))) -> dict[str, Any]:
        """Returns a labeled draft. It does not change the case."""
        v = _get_visible(case_id, p)
        d = summarize_case(_out(v, p), api_key=cfg.gemini_api_key, model=cfg.gemini_model)
        return {"text": d.text, "label": d.label, "model": d.model, "mock": d.mock}

    # -------------------------------------------------------------- admin

    @app.post("/api/admin/cases/{case_id}/verify-projection")
    def verify_projection(case_id: str, _: Principal = Depends(require(Perm.ADMIN))) -> dict[str, Any]:
        rebuilt = cmd.rebuild(repo, case_id)
        stored = repo.get_case(case_id)
        return {
            "case_id": case_id,
            "matches": stored is not None and stored.to_doc() == rebuilt.to_doc(),
            "version": rebuilt.version,
        }

    # -------------------------------------------------------------- imports

    async def _csv_text(request: Request) -> str:
        raw = await request.body()
        if len(raw) > MAX_CSV_BYTES:
            raise HTTPException(413, "CSV is larger than 5 MB.")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "CSV must be UTF-8.") from None

    @app.post("/api/imports/validate")
    async def import_validate(request: Request, _: Principal = Depends(require(Perm.IMPORT_CSV))):
        rep = validate_csv(await _csv_text(request))
        preview = [
            {"line": r.line, "record_id": r.row.get("record_id"), "errors": r.errors, "warnings": r.warnings}
            for r in rep.rows
            if r.errors or r.warnings
        ][:500]
        return {"summary": rep.summary(), "issues_preview": preview, "error_csv": rep.error_csv()}

    def _open_from_rows(rows: list[dict[str, str]], actor, synthetic: bool) -> dict[str, int]:
        opened = skipped = 0
        for row in rows:
            if row.get("severity") == "normal":
                skipped += 1
                continue
            pw = lib.match(row["screening_type"], row["result"], row["severity"])
            case_id = f"C-{row['record_id']}"
            if not pw or repo.get_case(case_id):
                skipped += 1
                continue
            cmd.open_case(
                repo,
                case_id=case_id,
                pathway=pw,
                actor=actor,
                owner=row.get("owner") or None,
                synthetic=synthetic or row.get("data_label") == LABEL,
                screening={
                    "participant_id": row["participant_id"],
                    "screening_id": row["record_id"],
                    "screening_type": row["screening_type"],
                    "result": row["result"],
                    "severity": row["severity"],
                    "screened_at": row["screened_at"],
                    "red_flag": row.get("red_flag") == "yes",
                },
            )
            opened += 1
        return {"opened": opened, "skipped": skipped}

    @app.post("/api/imports/commit")
    async def import_commit(request: Request, p: Principal = Depends(require(Perm.IMPORT_CSV))):
        rep = validate_csv(await _csv_text(request))
        if rep.file_errors:
            raise HTTPException(422, "; ".join(rep.file_errors))
        return {**_open_from_rows(rep.valid_rows, p.actor, synthetic=False), "summary": rep.summary()}

    @app.post("/api/demo/seed")
    def demo_seed(
        n: int = Body(1000, embed=True, le=5000),
        seed: int = Body(42, embed=True),
        _: Principal = Depends(require(Perm.ADMIN)),
    ) -> dict[str, Any]:
        if cfg.is_production and not cfg.allow_demo_auth_in_production:
            raise HTTPException(403, "Demo seeding is off in production.")
        cohort = generate(n, seed)
        import csv as _csv
        import io

        buf = io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=list(cohort.rows[0].keys()))
        w.writeheader()
        w.writerows(cohort.rows)
        rep = validate_csv(buf.getvalue())
        res = _open_from_rows(rep.valid_rows, SYSTEM_ACTOR, synthetic=True)
        return {"data_label": LABEL, "disclaimer": DISCLAIMER, **res, "validation": rep.summary()}

    return app
