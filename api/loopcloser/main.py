"""LoopCloser API (FastAPI on Cloud Run).

Care-continuity system, not a diagnostic AI. Deterministic rules decide; humans
review, escalate and close; Gemini only drafts text.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth
from .ai.assist import summarize_case
from .auth import Principal, require
from .config import Config, get_config
from .domain import commands as cmd
from .domain import ladder as ladder_mod
from .domain import priority as prio
from .domain.case import CaseView
from .domain.errors import DomainError
from .domain.events import SYSTEM_ACTOR, Actor
from .domain.next_action import recommend
from .domain.roles import Perm, Role, has_perm
from .domain.states import CaseState
from .imports.csv_validation import validate_csv
from .logging_setup import request_id_var, setup_logging, trace_var
from .pathways.library import PathwayLibrary, default_library
from .ratelimit import SlidingWindowLimiter
from .store.base import CaseRepository
from .synth.generator import DISCLAIMER, LABEL, generate
from .templates.library import TemplateError, default_templates

log = logging.getLogger("loopcloser")
SENSITIVE_PREFIXES = ("/api/imports", "/api/ai", "/api/demo", "/api/ladder")
MANILA = ZoneInfo("Asia/Manila")
SEED_ACTOR = Actor(id="demo-seed-history", role=Role.COORDINATOR, kind="human")
TIER_RANK = {"urgent": 0, "high": 1, "moderate": 2, "routine": 3}
MAX_CSV_BYTES = 5 * 1024 * 1024


def PHONE_OK(phone: str) -> bool:  # noqa: N802
    from .imports.csv_validation import PHONE_RE

    return bool(PHONE_RE.match(phone or ""))


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
    language: str = "en"
    comorbidity: bool = False
    barriers: list[str] = Field(default_factory=list)


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
    appointment: dict[str, str] | None = None


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


class BarrierIn(BaseModel):
    barrier: str
    resolution: str | None = Field(default=None, max_length=500)


class OverrideIn(BaseModel):
    tier: str | None
    reason: str
    note: str = Field(max_length=1000)


class MessageIn(BaseModel):
    template_id: str
    language: str = "en"
    channel: str = "sms"
    appointment_date: str | None = None
    clinic: str | None = None


class ClockIn(BaseModel):
    advance_days: int = Field(ge=0, le=30)


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
    templates = default_templates()
    steps = ladder_mod.load_ladder(cfg.ladder_json)
    clock = {"offset_days": 0}

    def now() -> datetime:
        """Simulated clock: real time plus the demo offset ("advance day")."""
        return datetime.now(UTC) + timedelta(days=clock["offset_days"])

    def today() -> date:
        return now().astimezone(MANILA).date()

    if cfg.demo_mode:
        log.warning("DEMO_MODE is on: role switcher enabled next to Firebase Auth")

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
        tpl_problems = templates.lock_mismatches()
        checks["templates"] = len(templates.latest()) if not tpl_problems else "lock mismatch"
        ok = checks["storage"] != "down" and not problems and not tpl_problems
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503
        )

    @app.get("/api/public-config")
    def public_config() -> dict[str, Any]:
        """No auth. Lets the static web app show the demo banner and role switcher at runtime."""
        return {
            "demo_mode": cfg.demo_mode,
            "version": cfg.version,
            "env": cfg.env,
            "auth": "Firebase Auth accounts with role permissions",
        }

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

    def _out(v: CaseView, p: Principal, detail: bool = False) -> dict[str, Any]:
        d = v.to_doc()
        if p.role.value != "patient":
            d["participant_id"] = mask_participant(v.participant_id)
        d.pop("patient_uid", None)
        d["priority"] = prio.compute(v, today()).to_dict()
        d["recommended_action"] = recommend(v)
        if detail:
            d["ladder"] = ladder_mod.status(v, today(), steps)
            d["day"] = ladder_mod.day_of(v, today())
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
        p: Principal = Depends(auth.current_user),
        state: CaseState | None = None,
        tier: str | None = None,
        owner: str | None = None,
        limit: int = Query(200, le=1000),
    ) -> dict[str, Any]:
        rows = [
            v
            for v in repo.list_cases()
            if _visible(v, p) and (state is None or v.state == state) and (owner is None or v.owner == owner)
        ]
        out = [_out(v, p) for v in rows]
        if tier:
            out = [c for c in out if c["priority"]["tier"] == tier]
        out.sort(
            key=lambda c: (
                c["state"] == "closed",
                TIER_RANK[c["priority"]["tier"]],
                -c["priority"]["score"],
                c["due_date"] or "9999",
                c["id"],
            )
        )
        counts: dict[str, int] = {}
        for c in out:
            counts[c["priority"]["tier"]] = counts.get(c["priority"]["tier"], 0) + 1
        return {"total": len(out), "today": today().isoformat(), "tier_counts": counts, "cases": out[:limit]}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str, p: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        return _out(_get_visible(case_id, p), p, detail=True)

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
            repo,
            case_id=case_id,
            screening=body.model_dump(mode="json"),
            pathway=pw,
            actor=p.actor,
            owner=body.owner,
            barriers=body.barriers,
            now=now(),
        )
        return _out(v, p)

    @app.post("/api/cases/{case_id}/assign")
    def assign(case_id: str, body: AssignIn, p: Principal = Depends(require(Perm.CASE_ASSIGN))):
        _get_visible(case_id, p)
        return _out(cmd.assign(repo, case_id, actor=p.actor, now=now(), **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/transition")
    def transition(case_id: str, body: TransitionIn, p: Principal = Depends(require(Perm.CASE_TRANSITION))):
        _get_visible(case_id, p)
        if body.target in {CaseState.RESOLVED_BY_HUMAN, CaseState.CLINICIAN_CONTACTED} and not has_perm(
            p.role, Perm.RED_FLAG_RESOLVE
        ):
            raise HTTPException(403, "Your role cannot resolve red flags.")
        payload = body.model_dump(mode="json", exclude={"target"}, exclude_none=True)
        return _out(cmd.transition(repo, case_id, body.target, actor=p.actor, payload=payload, now=now()), p)

    @app.post("/api/cases/{case_id}/contact-attempts")
    def contact(case_id: str, body: ContactIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        _get_visible(case_id, p)
        return _out(
            cmd.log_contact_attempt(
                repo, case_id, channel=body.channel, result=body.result, actor=p.actor, settings=settings, now=now()
            ),
            p,
        )

    @app.post("/api/cases/{case_id}/notifications")
    def notification(case_id: str, body: NotificationIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        """Simulated outbox status. No real SMS is sent."""
        _get_visible(case_id, p)
        return _out(cmd.record_notification(repo, case_id, actor=p.actor, now=now(), **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/red-flag")
    def red_flag(case_id: str, body: RedFlagIn, p: Principal = Depends(require(Perm.RED_FLAG_REPORT))):
        _get_visible(case_id, p)
        source = "patient" if p.role.value == "patient" else body.source
        return _out(cmd.report_red_flag(repo, case_id, actor=p.actor, source=source, code=body.code, now=now()), p)

    @app.post("/api/cases/{case_id}/resume-automation")
    def resume(case_id: str, body: ResumeIn, p: Principal = Depends(require(Perm.AUTOMATION_RESUME))):
        _get_visible(case_id, p)
        return _out(cmd.resume_automation(repo, case_id, actor=p.actor, reason=body.reason, now=now()), p)

    @app.post("/api/cases/{case_id}/close")
    def close(case_id: str, body: CloseIn, p: Principal = Depends(require(Perm.CASE_CLOSE))):
        _get_visible(case_id, p)
        return _out(cmd.close_case(repo, case_id, actor=p.actor, now=now(), **body.model_dump()), p)

    @app.post("/api/cases/{case_id}/notes")
    def note(case_id: str, body: NoteIn, p: Principal = Depends(require(Perm.CASE_NOTE))):
        _get_visible(case_id, p)
        return _out(cmd.add_note(repo, case_id, actor=p.actor, text=body.text, now=now()), p)

    @app.post("/api/cases/{case_id}/barriers")
    def barrier(case_id: str, body: BarrierIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        _get_visible(case_id, p)
        if body.resolution:
            v = cmd.resolve_barrier(
                repo, case_id, actor=p.actor, barrier=body.barrier, resolution=body.resolution, now=now()
            )
        else:
            v = cmd.report_barrier(repo, case_id, actor=p.actor, barrier=body.barrier, now=now())
        return _out(v, p)

    @app.post("/api/cases/{case_id}/priority-override")
    def priority_override(case_id: str, body: OverrideIn, p: Principal = Depends(require(Perm.PRIORITY_OVERRIDE))):
        _get_visible(case_id, p)
        v = cmd.override_priority(
            repo, case_id, actor=p.actor, tier=body.tier, reason=body.reason, note=body.note, now=now()
        )
        return _out(v, p, detail=True)

    @app.get("/api/priority/rules")
    def priority_rules(_: Principal = Depends(require(Perm.PATHWAY_READ))) -> dict[str, Any]:
        return {
            "rules": [{"rule_id": r, "points": pts, "label": lbl} for r, pts, lbl in prio.RULES],
            "tiers": {"urgent": "8+", "high": "5-7", "moderate": "3-4", "routine": "0-2"},
            "guidance": prio.TIER_GUIDANCE,
            "override_reasons": list(cmd.OVERRIDE_REASONS),
            "barriers": list(cmd.BARRIER_TYPES),
        }

    # -------------------------------------------------------------- templates (official messages)

    @app.get("/api/templates")
    def list_templates(_: Principal = Depends(require(Perm.PATHWAY_READ))) -> list[dict]:
        return [t.model_dump() for t in templates.latest()]

    def _render(v: CaseView, body: MessageIn) -> dict[str, Any]:
        tpl = templates.get(body.template_id)
        if tpl is None:
            raise HTTPException(422, "Unknown template. Official messages must use an approved template.")
        ctx = {
            "screening_type": v.screening_type,
            "pathway_id": v.pathway_id,
            "due_date": v.due_date.isoformat() if v.due_date else "",
            "clinic_phone": cfg.clinic_phone,
            "appointment_date": body.appointment_date or (v.appointment or {}).get("date"),
            "clinic": body.clinic or (v.appointment or {}).get("clinic"),
        }
        try:
            return tpl.render(body.language, ctx)
        except TemplateError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/cases/{case_id}/messages/preview")
    def message_preview(case_id: str, body: MessageIn, p: Principal = Depends(require(Perm.MESSAGE_SEND))):
        return _render(_get_visible(case_id, p), body)

    @app.post("/api/cases/{case_id}/messages")
    def message_send(case_id: str, body: MessageIn, p: Principal = Depends(require(Perm.MESSAGE_SEND))):
        """Simulated outbox: renders an approved template and logs it. Nothing is really sent."""
        v = _get_visible(case_id, p)
        msg = _render(v, body)
        v = cmd.record_notification(
            repo,
            case_id,
            status="sent",
            channel=body.channel,
            template_id=msg["template_id"],
            template_version=msg["template_version"],
            language=body.language,
            actor=p.actor,
            now=now(),
        )
        return {"message": msg, "simulated": True, "case": _out(v, p)}

    # -------------------------------------------------------------- clock and escalation ladder

    @app.get("/api/clock")
    def get_clock(_: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        return {
            "today": today().isoformat(),
            "offset_days": clock["offset_days"],
            "simulated": clock["offset_days"] > 0,
            "ladder": [{"day": s.day, "id": s.id, "label": s.label} for s in steps],
        }

    @app.post("/api/demo/clock")
    def advance_clock(body: ClockIn, _: Principal = Depends(require(Perm.ADMIN))) -> dict[str, Any]:
        if not cfg.demo_mode:
            raise HTTPException(403, "The simulated clock is only available in demo mode.")
        clock["offset_days"] += body.advance_days
        result = ladder_mod.run_all(repo, today=today(), now=now(), ladder=steps)
        return {"today": today().isoformat(), "offset_days": clock["offset_days"], "ladder": result}

    @app.post("/api/ladder/run")
    def run_ladder(_: Principal = Depends(require(Perm.ADMIN))) -> dict[str, Any]:
        """Run due ladder steps for all open cases (in production a Cloud Scheduler job would call this)."""
        return ladder_mod.run_all(repo, today=today(), now=now(), ladder=steps)

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
            barrier = row.get("barrier") or ""
            cmd.open_case(
                repo,
                case_id=case_id,
                pathway=pw,
                actor=actor,
                owner=row.get("owner") or None,
                synthetic=synthetic or row.get("data_label") == LABEL,
                barriers=[barrier] if barrier in cmd.BARRIER_TYPES else [],
                now=now(),
                screening={
                    "participant_id": row["participant_id"],
                    "screening_id": row["record_id"],
                    "screening_type": row["screening_type"],
                    "result": row["result"],
                    "severity": row["severity"],
                    "screened_at": row["screened_at"],
                    "red_flag": row.get("red_flag") == "yes",
                    "language": row.get("language") or "en",
                    "comorbidity": row.get("comorbidity") == "yes",
                    "location": row.get("location"),
                    "age_band": row.get("age_band"),
                    "phone_valid": bool(PHONE_OK(row.get("phone", ""))),
                },
            )
            if synthetic:
                _simulate_history(case_id, row)
            opened += 1
        return {"opened": opened, "skipped": skipped}

    def _simulate_history(case_id: str, row: dict[str, str]) -> None:
        """Walk SIMULATED cases forward to match their synthetic status, so the demo has variety."""
        status = row.get("status")
        v = repo.get_case(case_id)
        if status not in {"scheduled", "no_show"} or not v or v.automation_paused or not v.owner:
            return
        t = now()
        cmd.transition(repo, case_id, CaseState.REVIEWED, actor=SEED_ACTOR, now=t)
        cmd.log_contact_attempt(repo, case_id, channel="call", result="reached", actor=SEED_ACTOR, now=t)
        cmd.transition(repo, case_id, CaseState.PATIENT_NOTIFIED, actor=SEED_ACTOR, now=t)
        cmd.transition(
            repo,
            case_id,
            CaseState.UNDERSTANDING_CONFIRMED,
            actor=SEED_ACTOR,
            now=t,
            payload={"source": "staff_confirmed"},
        )
        appt = {"date": row.get("appointment_at") or "", "clinic": f"{row.get('location') or 'Site A'} clinic"}
        cmd.transition(
            repo,
            case_id,
            CaseState.ACTION_SCHEDULED,
            actor=SEED_ACTOR,
            now=t,
            payload={"appointment": appt, "note": "SIMULATED history"},
        )
        if status == "no_show":
            cmd.transition(repo, case_id, CaseState.NO_SHOW, actor=SEED_ACTOR, now=t, payload={"note": "SIMULATED"})

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
        if not cfg.demo_mode:
            raise HTTPException(403, "Demo seeding is only available in demo mode.")
        cohort = generate(n, seed, anchor=today())  # dates relative to the (simulated) today
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
