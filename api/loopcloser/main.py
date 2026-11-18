"""LoopCloser API (FastAPI on Cloud Run).

Care-continuity system, not a diagnostic AI. Deterministic rules decide; humans
review, escalate and close; Gemini only drafts text.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import auth
from .ai.assist import AI_LABEL, PROMPT_VERSION, AIBackend, prepare_call, summarize_case
from .auth import Principal, require
from .config import Config, get_config
from .domain import commands as cmd
from .domain import gates as gates_mod
from .domain import indexing as idx
from .domain import ladder as ladder_mod
from .domain import priority as prio
from .domain.case import CaseView
from .domain.errors import DomainError, GuardViolation
from .domain.events import SYSTEM_ACTOR, Actor, Event, EventType
from .domain.next_action import PLAIN_STATUSES, lost_contact, plain_status, recommend
from .domain.roles import Perm, Role, has_perm
from .domain.states import CaseState
from .fhir import importer as fhir_mod
from .imports.csv_validation import validate_csv
from .logging_setup import request_id_var, setup_logging, trace_var
from .pathways.library import PathwayLibrary, default_library
from .ratelimit import SlidingWindowLimiter
from .store.base import CaseRepository
from .synth.generator import DISCLAIMER, LABEL, generate
from .synth.stories import play_stories
from .templates.library import TemplateError, default_templates

log = logging.getLogger("loopcloser")
SENSITIVE_PREFIXES = ("/api/imports", "/api/ai", "/api/demo", "/api/ladder", "/api/fhir")
SCREENING_TYPES = frozenset({"fit", "bp", "cervical", "generic", "symptom"})
MANILA = ZoneInfo("Asia/Manila")
SEED_ACTOR = Actor(id="demo-seed-history", role=Role.COORDINATOR, kind="human")
MAX_CSV_BYTES = 5 * 1024 * 1024


def PHONE_OK(phone: str) -> bool:  # noqa: N802
    from .imports.csv_validation import PHONE_RE

    return bool(PHONE_RE.match(phone or ""))


CONTENT_KINDS = {
    "recorded_fact": "Recorded fact: data on file, entered or uploaded by a person",
    "rule_result": "Rule result: a deterministic calculation, deadline or automated rule step",
    "ai_written": "AI-written: a Gemini draft for staff; it never changes the case",
}


def content_kind(e: Event) -> str:
    """Which of the three kinds of content an event is (shown on the case page and in every export)."""
    if e.type in {EventType.AI_DRAFT_CREATED}:
        return "ai_written"
    if e.type == EventType.LADDER_STEP or e.actor.kind != "human":
        return "rule_result"
    return "recorded_fact"


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
    contact_consent: Literal["yes", "no"] | None = None  # None: not recorded, so calls and SMS hold (GATE-1)


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


class EvidenceIn(BaseModel):
    visit_date: str = Field(max_length=10)
    facility: str = Field(max_length=120)
    record_number: str = Field(max_length=40)


class CloseIn(BaseModel):
    closure_reason: str = Field(max_length=500)
    evidence: EvidenceIn | None = None
    evidence_ref: str | None = Field(default=None, max_length=200)  # legacy reference id (e.g. an upload id)
    sign_off: bool = False


class RevealIn(BaseModel):
    fields: list[str] = Field(default_factory=lambda: ["name", "phone"])


class ConsentIn(BaseModel):
    consent: Literal["yes", "no"]
    source: str = Field(max_length=200)


class SmsReplyIn(BaseModel):
    keyword: Literal["YES", "RESCHED", "STOP"]


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


class DecisionIn(BaseModel):
    decision: str


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
    clock: dict[str, Any] = {"offset_days": 0, "checked": 0.0}
    ai_backend = AIBackend(
        kind=cfg.gemini_backend,
        model=cfg.gemini_model,
        project=cfg.vertex_project,
        location=cfg.vertex_location,
        api_key=cfg.gemini_api_key,
    )
    indexed: dict[str, Any] = {"as_of": None, "full": False}

    def _refresh_clock() -> None:
        """The demo clock is stored in Firestore (meta/clock) so it survives restarts and an operator reset
        (scripts/reset_demo.py) is picked up within 30 seconds."""
        if not cfg.demo_mode or time.monotonic() - clock["checked"] < 30:
            return
        clock["checked"] = time.monotonic()
        try:
            stored = int(repo.get_meta("clock").get("offset_days", 0))
        except Exception:  # noqa: BLE001 - never block a request on the demo clock
            log.exception("could not read the demo clock")
            return
        if stored < clock["offset_days"]:
            indexed["full"] = True  # clock went back: stored priorities are for a later date
        clock["offset_days"] = stored

    def now() -> datetime:
        """Simulated clock: real time plus the demo offset ("advance day")."""
        _refresh_clock()
        return datetime.now(UTC) + timedelta(days=clock["offset_days"])

    def today() -> date:
        return now().astimezone(MANILA).date()

    repo.indexer = lambda v: idx.index_fields(v, today(), steps)

    def ensure_indexed() -> None:
        """Once per (simulated) day, refresh the stored tier and lane of cases whose due date crossed a threshold."""
        t = today().isoformat()
        if indexed["as_of"] is None:  # first call on this instance: were fields stored for a later date?
            stored = repo.get_meta("index").get("as_of")
            indexed["full"] = indexed["full"] or bool(stored and stored > t)
        if indexed["as_of"] != t or indexed["full"]:
            n = repo.reindex(t, everything=indexed["full"])
            indexed["as_of"], indexed["full"] = t, False
            repo.set_meta("index", {"as_of": t})
            if n:
                log.info("reindexed cases", extra={"fields": {"count": n, "as_of": t}})

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

    # Auto-refresh: a counter of successful writes on this instance, bumped by the middleware below. Pages poll
    # GET /api/changes (no database read) and reload only when it moves. The demo runs one instance (max 1);
    # with more, a page still reloads on its own every 2 minutes.
    changes: dict[str, Any] = {"boot": uuid.uuid4().hex[:8], "n": 0}

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
        if path.startswith("/api/") and request.method == "POST" and response.status_code < 400:
            changes["n"] += 1  # what the Today and case pages poll (GET /api/changes)
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
        checks["ai"] = (
            f"gemini via {ai_backend.kind} ({ai_backend.model}, {ai_backend.location})" if ai_backend.live else "mock"
        )
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

    @app.get("/api/changes")
    def changes_view(_: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        """Cheap poll for auto-refresh: changes when any case or the demo clock changed. No database read."""
        return {"version": f"{changes['boot']}-{changes['n']}"}

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
        t = today()
        d["priority"] = prio.compute(v, t).to_dict()
        d["recommended_action"] = recommend(v)
        d["plain_status"] = plain_status(v)
        d["plain_status_label"] = PLAIN_STATUSES[d["plain_status"]]
        d["lost_contact"] = lost_contact(v)
        d["days_to_due"] = (v.due_date - t).days if v.due_date else None
        d["gates_on_hold"] = [g["id"] for g in gates_mod.holds(v)] if v.state != CaseState.CLOSED else []
        if detail:
            d["gates"] = gates_mod.compute(v)
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

    def _scope(p: Principal) -> dict[str, str]:
        """Which cases a role may list, as a query filter (same rule as _visible)."""
        if has_perm(p.role, Perm.CASE_READ_ALL):
            return {}
        if has_perm(p.role, Perm.CASE_READ_ASSIGNED):
            return {"person": p.uid}
        if has_perm(p.role, Perm.CASE_READ_OWN):
            return {"patient": p.uid}
        raise HTTPException(403, "Not allowed.")

    def _tier_counts(scope: dict[str, Any]) -> dict[str, int]:
        return {t: repo.count(tier=t, **scope) for t in idx.TIERS}

    def _filters(p: Principal, mine: bool, screening_type: str | None) -> dict[str, Any]:
        """The role scope plus the optional "My cases" and screening-type filters."""
        scope: dict[str, Any] = dict(_scope(p))
        if mine and "patient" not in scope:
            scope["person"] = p.uid
        if screening_type:
            if screening_type not in SCREENING_TYPES:
                raise HTTPException(400, f"screening_type must be one of {', '.join(sorted(SCREENING_TYPES))}")
            scope["screening_type"] = screening_type
        return scope

    @app.get("/api/today")
    def today_view(
        p: Principal = Depends(auth.current_user),
        per_lane: int = Query(15, ge=1, le=100),
        mine: bool = False,
        screening_type: str | None = None,
    ) -> dict[str, Any]:
        """Staff Today view: the top cases of each lane plus exact counts, without reading every case.
        Cost per load: per_lane documents per lane plus a few aggregation counts."""
        ensure_indexed()
        scope = _filters(p, mine, screening_type)
        lanes = {}
        for lane in idx.LANES:
            rows = repo.query(lane=lane, limit=per_lane, **scope)
            lanes[lane] = {"count": repo.count(lane=lane, **scope), "cases": [_out(v, p) for v in rows]}
        return {
            "today": today().isoformat(),
            "total": sum(x["count"] for x in lanes.values()),
            "tier_counts": _tier_counts(scope),
            "summary": {
                "to_contact": repo.count(status="to_contact", **scope),
                "overdue": lanes["overdue"]["count"],
                "lost_contact": repo.count(lost=True, **scope),
                "needs_review": repo.count(status="needs_review", **scope),
            },
            "filters": {"mine": mine, "screening_type": screening_type},
            "lanes": lanes,
        }

    @app.get("/api/cases")
    def list_cases(
        p: Principal = Depends(auth.current_user),
        lane: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        mine: bool = False,
        screening_type: str | None = None,
    ) -> dict[str, Any]:
        """Cases you can see, highest priority first, optionally one lane. Reads at most `limit` documents."""
        if lane is not None and lane not in idx.LANES:
            raise HTTPException(400, f"lane must be one of {', '.join(idx.LANES)}")
        ensure_indexed()
        scope = _filters(p, mine, screening_type)
        rows = repo.query(lane=lane, limit=limit, **scope)
        return {
            "total": repo.count(lane=lane, **scope),
            "today": today().isoformat(),
            "tier_counts": _tier_counts(scope),
            "cases": [_out(v, p) for v in rows],
        }

    @app.get("/api/cases/search")
    def search_cases(
        q: str = Query(..., min_length=2, max_length=40), p: Principal = Depends(auth.current_user)
    ) -> dict[str, Any]:
        """Find cases by case id (prefix; "DEMO-01" also finds "C-DEMO-01"). Names are not searchable on
        purpose: they stay hidden until a staff member reveals them, and every reveal is logged."""
        if p.role.value == "patient":
            raise HTTPException(403, "Not allowed.")
        term = q.strip().upper()
        ids: list[str] = []
        for prefix in dict.fromkeys([term, term if term.startswith("C-") else f"C-{term}"]):
            ids += [i for i in repo.search_ids(prefix, 20) if i not in ids]
        found = [v for v in (repo.get_case(i) for i in ids[:20]) if v and _visible(v, p)]
        return {"query": q, "cases": [_out(v, p) for v in found]}

    @app.get("/api/dashboard")
    def dashboard(p: Principal = Depends(require(Perm.DASHBOARD_READ))) -> dict[str, Any]:
        """Program manager view. Every number is computed from the case projections, which are folds of the
        event log, and from the log itself for the time to care. Reads every case: fine for a demo or one
        health unit; a large program would keep these as running totals."""
        t = today()
        cases = repo.list_cases()
        total = len(cases)
        closed = [v for v in cases if v.state == CaseState.CLOSED]
        open_ = [v for v in cases if v.state != CaseState.CLOSED]
        overdue = [v for v in open_ if idx.lane_for(v, t) == "overdue"]
        lost = [v for v in open_ if lost_contact(v)]
        done_ids = [v.id for v in cases if v.state in {CaseState.VISIT_COMPLETED, CaseState.CLOSED}]
        days: list[int] = []
        for evs in repo.load_events_many(done_ids).values():
            opened = next((e.at for e in evs if e.type.value == "case_opened"), None)
            visit = next(
                (
                    e.at
                    for e in evs
                    if e.type.value == "state_changed" and e.payload.get("to") == CaseState.VISIT_COMPLETED.value
                ),
                None,
            )
            if opened and visit:
                days.append((visit - opened).days)
        days.sort()
        median = None
        if days:
            mid = len(days) // 2
            median = days[mid] if len(days) % 2 else (days[mid - 1] + days[mid]) / 2
        by_status = {k: 0 for k in PLAIN_STATUSES}
        for v in cases:
            by_status[plain_status(v)] += 1
        by_type: dict[str, dict[str, int]] = {}
        for v in cases:
            row = by_type.setdefault(v.screening_type, {"total": 0, "closed": 0, "overdue": 0})
            row["total"] += 1
            row["closed"] += v.state == CaseState.CLOSED
            row["overdue"] += v.state != CaseState.CLOSED and idx.lane_for(v, t) == "overdue"
        return {
            "today": t.isoformat(),
            "total_cases": total,
            "closed": len(closed),
            "closure_rate": round(len(closed) / total, 3) if total else None,
            "closed_with_evidence": sum(1 for v in closed if v.closure_evidence),
            "closed_with_signoff": sum(1 for v in closed if v.signed_off_by and not v.closure_evidence),
            "median_days_to_care": median,
            "days_to_care_n": len(days),
            "open": len(open_),
            "overdue": len(overdue),
            "lost_to_follow_up": len(lost),
            "unowned_open": sum(1 for v in open_ if not v.owner),
            "red_flags_open": sum(1 for v in open_ if v.red_flag_open),
            "escalated_open": sum(1 for v in open_ if v.state == CaseState.ESCALATED),
            "by_status": {PLAIN_STATUSES[k]: n for k, n in by_status.items()},
            "by_screening_type": dict(sorted(by_type.items())),
            "synthetic_share": round(sum(1 for v in cases if v.synthetic) / total, 3) if total else None,
            "definitions": {
                "closure_rate": "closed cases / all cases",
                "median_days_to_care": "days from the case being opened to the visit being recorded, "
                "over cases with a recorded visit",
                "overdue": "open cases past their pathway deadline (visit not completed)",
                "lost_to_follow_up": "open cases marked unable to reach, or with 3+ failed contact attempts and "
                "no successful one",
            },
        }

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

    def _check_contact_gates(v: CaseView, channel: str) -> None:
        """Rule GATE-1: no patient contact on a channel while a gate that blocks it is on Hold."""
        held = gates_mod.blocking(v, channel)
        if held:
            raise GuardViolation(
                "On hold: " + " ".join(f"{g['label']}: {g['missing']}" for g in held), rule_id=gates_mod.RULE_ID
            )

    @app.post("/api/cases/{case_id}/contact-attempts")
    def contact(case_id: str, body: ContactIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        _check_contact_gates(_get_visible(case_id, p), body.channel)
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
        v = cmd.close_case(
            repo,
            case_id,
            actor=p.actor,
            closure_reason=body.closure_reason,
            evidence=body.evidence.model_dump() if body.evidence else None,
            evidence_ref=body.evidence_ref,
            sign_off=body.sign_off,
            now=now(),
            today=today(),
        )
        return _out(v, p)

    @app.post("/api/cases/{case_id}/reveal-contact")
    def reveal_contact(case_id: str, body: RevealIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        """Show the fictional name and phone of a SIMULATED case. Logged as an event (rule PRIV-1): which
        fields and who, never the values. Real imports keep no names or phones in this build."""
        v = _get_visible(case_id, p)
        contact = repo.get_contact(v.participant_id) if v.synthetic else None
        if not contact:
            raise HTTPException(404, "No contact details on file for this case.")
        fields = tuple(dict.fromkeys(body.fields))
        cmd.record_contact_reveal(repo, case_id, actor=p.actor, fields=fields, now=now())
        return {
            "case_id": case_id,
            **{f: contact.get(f) or "" for f in fields},
            "data_label": "SIMULATED",
            "logged": True,
        }

    @app.get("/api/cases/{case_id}/outbox")
    def outbox(case_id: str, p: Principal = Depends(auth.current_user)) -> dict[str, Any]:
        """The simulated SMS this patient was sent, re-rendered from each logged template id, version and
        language with the case record. Nothing is ever really sent."""
        if p.role.value == "program_manager":
            raise HTTPException(403, "Not allowed.")
        v = _get_visible(case_id, p)
        msgs = []
        for e in repo.load_events(case_id):
            if e.type == EventType.SMS_REPLY_RECEIVED:
                msgs.append(
                    {
                        "at": e.at.isoformat(),
                        "direction": "in",
                        "template_id": None,
                        "language": v.language,
                        "channel": "sms",
                        "by_automation": False,
                        "text": e.payload.get("keyword"),
                    }
                )
                continue
            if e.type.value != "notification_status" or e.payload.get("status") != "sent":
                continue
            tpl = templates.get(e.payload["template_id"], e.payload.get("template_version"))
            lang = e.payload.get("language", "en")
            text = None
            if tpl is not None and lang in tpl.languages:
                try:
                    text = tpl.render(lang, _msg_ctx(v, None, None))["text"]
                except TemplateError:
                    text = None
            msgs.append(
                {
                    "at": e.at.isoformat(),
                    "direction": "out",
                    "template_id": e.payload["template_id"],
                    "language": lang,
                    "channel": e.payload.get("channel", "sms"),
                    "by_automation": e.actor.kind != "human",
                    "text": text,
                }
            )
        return {
            "case_id": case_id,
            "participant_id": _out(v, p)["participant_id"],
            "language": v.language,
            "simulated": True,
            "sms_opt_out": v.sms_opt_out,
            "state": v.state.value,
            "can_reply": v.state != CaseState.CLOSED and any(m["direction"] == "out" for m in msgs),
            "messages": msgs,
        }

    @app.post("/api/cases/{case_id}/consent")
    def consent(case_id: str, body: ConsentIn, p: Principal = Depends(require(Perm.CASE_CONTACT))):
        """Record consent to contact, with its source (rule GATE-1). Logged as an event."""
        _get_visible(case_id, p)
        return _out(
            cmd.record_consent(repo, case_id, actor=p.actor, consent=body.consent, source=body.source, now=now()),
            p,
            detail=True,
        )

    @app.post("/api/cases/{case_id}/sms-replies")
    def sms_reply(case_id: str, body: SmsReplyIn, p: Principal = Depends(auth.current_user)):
        """Simulated patient SMS reply (rule MSG-4), posted by the mock phone page. Demo mode only: a real build
        would receive these from an SMS gateway webhook. Logged as the patient's phone, with who pressed it."""
        if not cfg.demo_mode:
            raise HTTPException(403, "Simulated SMS replies are only available in demo mode.")
        if not (has_perm(p.role, Perm.CASE_CONTACT) or has_perm(p.role, Perm.PATIENT_RESPOND)):
            raise HTTPException(403, f"Your role ({p.role.value}) cannot do this.")
        _get_visible(case_id, p)
        v = cmd.record_sms_reply(repo, case_id, keyword=body.keyword, entered_by=p.actor, now=now())
        return _out(v, p, detail=True)

    # -------------------------------------------------------------- FHIR R4 import (pasted or sample Bundle)

    def _fhir_plan(bundle: Any) -> fhir_mod.ImportPlan:
        try:
            return fhir_mod.plan_import(bundle, today=today())
        except fhir_mod.BundleError as exc:
            raise HTTPException(422, str(exc)) from None

    async def _fhir_body(request: Request) -> Any:
        raw = await request.body()
        if len(raw) > fhir_mod.MAX_BYTES:
            raise HTTPException(413, f"Bundle too large. At most {fhir_mod.MAX_BYTES // 1024} KB.")
        try:
            import json as _json

            data = _json.loads(raw or b"null")
        except ValueError:
            raise HTTPException(422, "Not valid JSON. Paste a FHIR R4 Bundle in JSON format.") from None
        return data.get("bundle", data) if isinstance(data, dict) and "bundle" in data else data

    @app.get("/api/fhir/sample")
    def fhir_sample(kind: str = "fit", _: Principal = Depends(require(Perm.IMPORT_CSV))) -> dict[str, Any]:
        """A SYNTHETIC FHIR R4 Bundle (fresh identifiers each call). Nothing is fetched from any server."""
        if kind not in fhir_mod.SAMPLE_KINDS:
            raise HTTPException(400, f"kind must be one of {', '.join(fhir_mod.SAMPLE_KINDS)}")
        return fhir_mod.sample_bundle(kind, today=today())

    @app.post("/api/fhir/import/validate")
    async def fhir_validate(request: Request, _: Principal = Depends(require(Perm.IMPORT_CSV))) -> dict[str, Any]:
        plan = _fhir_plan(await _fhir_body(request))
        items = []
        for m in plan.items:
            d = m.to_dict()
            if m.case_id and repo.get_case(m.case_id):
                d["status"], d["messages"] = "skipped", [*m.messages, f"Already imported as {m.case_id}."]
            items.append(d)
        return {"synthetic": plan.synthetic, "warnings": plan.warnings, "items": items}

    @app.post("/api/fhir/import")
    async def fhir_import(request: Request, p: Principal = Depends(require(Perm.IMPORT_CSV))) -> dict[str, Any]:
        """Open a case for each final, flagged result in the Bundle. Same domain commands and guards as any case;
        consent starts not recorded (GATE-1); names and phones are never stored."""
        plan = _fhir_plan(await _fhir_body(request))
        items, opened = [], []
        for m in plan.items:
            d = m.to_dict()
            if m.status == "ready" and m.screening and m.case_id:
                pw = lib.match(m.screening["screening_type"], m.screening["result"], m.screening["severity"])
                if repo.get_case(m.case_id):
                    d["status"], d["messages"] = "skipped", [*m.messages, f"Already imported as {m.case_id}."]
                elif pw is None:
                    d["status"], d["messages"] = "error", [*m.messages, "No pathway matches this result."]
                else:
                    source = {**(m.source or {}), **({"referral": m.referral} if m.referral else {})}
                    v = cmd.open_case(
                        repo,
                        case_id=m.case_id,
                        screening=m.screening,
                        pathway=pw,
                        actor=p.actor,
                        synthetic=plan.synthetic,
                        source=source,
                        now=now(),
                    )
                    d["status"] = "opened"
                    opened.append(_out(v, p))
            items.append(d)
        return {"synthetic": plan.synthetic, "warnings": plan.warnings, "items": items, "opened": opened}

    # -------------------------------------------------------------- downloads (staff only, logged: PRIV-2)

    def _export_events(case_id: str, p: Principal, kind: str) -> tuple[CaseView, list[Event]]:
        v = _get_visible(case_id, p)
        cmd.record_export(repo, case_id, actor=p.actor, kind=kind, now=now())
        return v, repo.load_events(case_id)

    def _export_name(case_id: str, ext: str) -> dict[str, str]:
        safe = "".join(ch for ch in case_id if ch.isalnum() or ch in "-_")
        return {"Content-Disposition": f'attachment; filename="{safe}-audit-trail.{ext}"'}

    def _export_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Downloads mask the participant id and drop the patient's login id (files travel further than screens)."""
        out = {k: val for k, val in payload.items() if k != "patient_uid"}
        if isinstance(out.get("participant_id"), str):
            out["participant_id"] = mask_participant(out["participant_id"])
        return out

    def _audit_rows(events: list[Event]) -> list[dict[str, Any]]:
        return [
            {
                "seq": e.seq,
                "at": e.at.isoformat(),
                "type": e.type.value,
                "content_kind": content_kind(e),
                "actor_id": e.actor.id,
                "actor_role": e.actor.role.value,
                "actor_kind": e.actor.kind,
                "rule_id": e.rule_id or "",
                "payload": _export_payload(e.payload),
            }
            for e in events
        ]

    @app.get("/api/cases/{case_id}/export/audit.json")
    def export_audit_json(case_id: str, p: Principal = Depends(require(Perm.EVENTS_READ))) -> JSONResponse:
        v, events = _export_events(case_id, p, "audit_json")
        body = {
            "case_id": v.id,
            "participant_id": mask_participant(v.participant_id),
            "exported_at": datetime.now(UTC).isoformat(),
            "exported_by": f"{p.uid} ({p.role.value})",
            "data_label": "SIMULATED" if v.synthetic else None,
            "note": "Append-only event log. Names and phone numbers are never in the log.",
            "content_kinds": CONTENT_KINDS,
            "events": _audit_rows(events),
        }
        return JSONResponse(body, headers=_export_name(case_id, "json"))

    @app.get("/api/cases/{case_id}/export/audit.csv")
    def export_audit_csv(case_id: str, p: Principal = Depends(require(Perm.EVENTS_READ))) -> Response:
        import csv as _csv
        import io
        import json as _json

        v, events = _export_events(case_id, p, "audit_csv")
        buf = io.StringIO()
        cols = ["seq", "at", "type", "content_kind", "actor_id", "actor_role", "actor_kind", "rule_id", "payload"]
        w = _csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        for row in _audit_rows(events):
            # The payload is one JSON object per cell, so a cell never starts with a formula character.
            w.writerow({**row, "payload": _json.dumps(row["payload"], ensure_ascii=False, sort_keys=True)})
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers=_export_name(case_id, "csv"))

    @app.get("/api/cases/{case_id}/export/summary")
    def export_summary(case_id: str, p: Principal = Depends(require(Perm.EVENTS_READ))) -> dict[str, Any]:
        """Printable case summary. Every section says what kind of content it is: recorded fact, rule result,
        or AI-written. The web app renders it on /case/print for the browser's Print or Save as PDF."""
        v, events = _export_events(case_id, p, "summary")
        d = _out(v, p, detail=True)
        draft = _draft_out(cmd.latest_ai_draft(repo, case_id))
        return {
            "case_id": v.id,
            "generated_at": datetime.now(UTC).isoformat(),
            "generated_by": f"{p.uid} ({p.role.value})",
            "data_label": "SIMULATED" if v.synthetic else None,
            "content_kinds": CONTENT_KINDS,
            "recorded_facts": {
                "participant_id": d["participant_id"],
                "screening_type": v.screening_type,
                "screening_id": v.screening_id,
                "severity": v.severity,
                "language": v.language,
                "owner": v.owner,
                "contact_consent": v.contact_consent or "not recorded",
                "valid_phone_on_file": v.phone_valid,
                "contact_attempts": v.contact_attempts,
                "reached_contacts": v.reached_contacts,
                "barriers_open": v.barriers_open,
                "appointment": v.appointment,
                "closure_reason": v.closure_reason,
                "closure_evidence": v.closure_evidence_detail,
                "signed_off_by": v.signed_off_by,
            },
            "rule_results": {
                "state": v.state.value,
                "plain_status": d["plain_status_label"],
                "pathway": f"{v.pathway_id} v{v.pathway_version} ({v.pathway_signoff_status})",
                "due_date": v.due_date.isoformat() if v.due_date else None,
                "days_to_due": d["days_to_due"],
                "priority": d["priority"],
                "recommended_action": d["recommended_action"],
                "gates": d["gates"],
                "ladder": d["ladder"],
            },
            "ai_written": (
                {
                    "label": draft["label"],
                    "model": draft["model"],
                    "verified": draft["verified"],
                    "text": draft["text"],
                    "decision": draft["decision"],
                    "decided_by": draft["decided_by"],
                }
                if draft
                else None
            ),
            "timeline": _audit_rows(events),
        }

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

    def _msg_ctx(v: CaseView, appointment_date: str | None, clinic: str | None) -> dict[str, Any]:
        return {
            "screening_type": v.screening_type,
            "pathway_id": v.pathway_id,
            "due_date": v.due_date.isoformat() if v.due_date else "",
            "clinic_phone": cfg.clinic_phone,
            "appointment_date": appointment_date or (v.appointment or {}).get("date"),
            "clinic": clinic or (v.appointment or {}).get("clinic"),
        }

    def _render(v: CaseView, body: MessageIn) -> dict[str, Any]:
        tpl = templates.get(body.template_id)
        if tpl is None:
            raise HTTPException(422, "Unknown template. Official messages must use an approved template.")
        ctx = _msg_ctx(v, body.appointment_date, body.clinic)
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
        _check_contact_gates(v, body.channel)
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
        _refresh_clock()
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
        clock["checked"] = 0.0
        _refresh_clock()  # start from the stored value, not a stale copy
        clock["offset_days"] += body.advance_days
        repo.set_meta("clock", {"offset_days": clock["offset_days"], "updated_at": datetime.now(UTC).isoformat()})
        result = _daily_run()
        return {"today": today().isoformat(), "offset_days": clock["offset_days"], "ladder": result}

    def _daily_run() -> dict[str, Any]:
        started = time.monotonic()
        result = ladder_mod.run_all(repo, today=today(), now=now(), ladder=steps)
        result["reindexed"] = repo.reindex(today().isoformat())
        indexed["as_of"] = today().isoformat()
        repo.set_meta("index", {"as_of": indexed["as_of"]})
        result["seconds"] = round(time.monotonic() - started, 2)
        log.info("ladder run", extra={"fields": result})
        return result

    @app.post("/api/ladder/run")
    def run_ladder(_: Principal = Depends(require(Perm.ADMIN))) -> dict[str, Any]:
        """Run due ladder steps (in production a Cloud Scheduler job would call this once a day)."""
        return _daily_run()

    @app.post("/api/admin/reindex")
    def reindex_all(_: Principal = Depends(require(Perm.ADMIN))) -> dict[str, Any]:
        """Recompute the stored query fields of every case (after a code change to priority or lanes)."""
        n = repo.reindex(today().isoformat(), everything=True)
        indexed["as_of"] = today().isoformat()
        return {"reindexed": n, "as_of": today().isoformat()}

    @app.post("/api/ai/cases/{case_id}/summary")
    def ai_summary(case_id: str, p: Principal = Depends(require(Perm.CASE_NOTE))) -> dict[str, Any]:
        """Returns a labeled draft. It does not change the case."""
        v = _get_visible(case_id, p)
        d = summarize_case(_out(v, p), backend=ai_backend)
        return {"text": d.text, "label": d.label, "model": d.model, "mock": d.mock}

    def _call_facts(v: CaseView) -> dict[str, Any]:
        """Masked facts for the call-prep draft. No names, phones or free-text notes."""
        t = today()
        pr = prio.compute(v, t)
        pw = lib.get(v.pathway_id, v.pathway_version)
        facts: dict[str, Any] = {
            "case_id": v.id,
            "today": t.isoformat(),
            "status": v.state.value.replace("_", " "),
            "screening_type": v.screening_type,
            "pathway": pw.name if pw else v.pathway_id,
            "next_action": v.next_action,
            "due_date": v.due_date.isoformat() if v.due_date else None,
            "contact_attempts": v.contact_attempts,
            "failed_contact_attempts": v.failed_contact_attempts,
            "reached_contacts": v.reached_contacts,
            "missed_appointments": v.no_show_count,
            "open_barriers": list(v.barriers_open),
            "patient_language": {"en": "English", "fil": "Filipino"}.get(v.language, v.language),
            "follow_up_priority": f"{pr.tier} ({pr.score} points)",
            "priority_reasons": [r["label"] for r in pr.reasons],
            # Chosen by rule, not by the model: which approved template fits this step.
            "approved_template_to_use": (
                "result-notice"
                if v.state == CaseState.REVIEWED
                else "booking-confirmation"
                if v.state == CaseState.ACTION_SCHEDULED
                else "reminder"
            ),
        }
        if v.due_date:
            days = (v.due_date - t).days
            facts["days_until_due" if days >= 0 else "days_overdue"] = abs(days)
        if v.appointment:
            facts["appointment"] = {k: v.appointment.get(k) for k in ("date", "clinic", "site") if v.appointment.get(k)}
        return facts

    def _draft_out(d: dict[str, Any] | None) -> dict[str, Any] | None:
        """What staff see. Unverified text is withheld, with the reason."""
        if d is None:
            return None
        verified = bool(d.get("verified"))
        return {
            "draft_seq": d["draft_seq"],
            "at": d["at"],
            "by": d["by"],
            "label": AI_LABEL,
            "model": d.get("model"),
            "mock": d.get("mock", True),
            "verified": verified,
            "text": d.get("text") if verified else None,
            "unsupported": d.get("unsupported", []),
            "checked_count": d.get("checked_count", 0),
            "decision": d.get("decision"),
            "decided_by": d.get("decided_by"),
        }

    @app.post("/api/ai/cases/{case_id}/call-prep")
    def call_prep(case_id: str, p: Principal = Depends(require(Perm.CASE_NOTE))) -> dict[str, Any]:
        """Staff-only AI draft to read before phoning the patient. Logged as an event; changes nothing else."""
        _get_visible(case_id, p)
        v = cmd.check_ai_draft_allowed(repo, case_id, actor=p.actor)
        facts = _call_facts(v)
        d = prepare_call(facts, backend=ai_backend)
        ver = d.verification
        payload = {
            "kind": "call_prep",
            "prompt_version": PROMPT_VERSION,
            "model": d.model,
            "mock": d.mock,
            "text": d.text,
            "verified": bool(ver and ver.verified),
            "unsupported": ver.unsupported if ver else [],
            "checked_count": len(ver.checked) if ver else 0,
            "usage": d.usage,
            "latency_ms": d.latency_ms,
        }
        log.info(
            "ai draft",
            extra={
                "fields": {
                    "case": case_id,
                    "model": d.model,
                    "mock": d.mock,
                    "verified": payload["verified"],
                    "usage": d.usage,
                    "latency_ms": d.latency_ms,
                }
            },
        )
        _, seq = cmd.record_ai_draft(repo, case_id, actor=p.actor, payload=payload, now=now())
        return {"draft": _draft_out(cmd.latest_ai_draft(repo, case_id)), "draft_seq": seq}

    @app.get("/api/ai/cases/{case_id}/call-prep")
    def call_prep_latest(case_id: str, p: Principal = Depends(require(Perm.CASE_NOTE))) -> dict[str, Any]:
        _get_visible(case_id, p)
        return {"draft": _draft_out(cmd.latest_ai_draft(repo, case_id))}

    @app.post("/api/ai/cases/{case_id}/call-prep/{draft_seq}/decision")
    def call_prep_decision(
        case_id: str, draft_seq: int, body: DecisionIn, p: Principal = Depends(require(Perm.CASE_NOTE))
    ) -> dict[str, Any]:
        """Use or Discard. Audit only: the case state does not change."""
        _get_visible(case_id, p)
        cmd.decide_ai_draft(repo, case_id, actor=p.actor, draft_seq=draft_seq, decision=body.decision, now=now())
        return {"draft": _draft_out(cmd.latest_ai_draft(repo, case_id))}

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
        rep = validate_csv(await _csv_text(request), today=today())
        preview = [
            {"line": r.line, "record_id": r.row.get("record_id"), "errors": r.errors, "warnings": r.warnings}
            for r in rep.rows
            if r.errors or r.warnings
        ][:500]
        return {"summary": rep.summary(), "issues_preview": preview, "error_csv": rep.error_csv()}

    def _open_from_rows(rows: list[dict[str, str]], actor, synthetic: bool, stories: bool = False) -> dict[str, int]:
        # Build new cases in a scratch in-memory store (same domain commands and guards), then write them
        # in bulk. Seeding 1,000 cases one transaction at a time took minutes on Firestore.
        from .store.memory import MemoryRepository

        stage = MemoryRepository()
        existing = repo.existing_ids()
        opened = skipped = 0
        for row in rows:
            if row.get("severity") == "normal":
                skipped += 1
                continue
            pw = lib.match(row["screening_type"], row["result"], row["severity"])
            case_id = f"C-{row['record_id']}"
            if not pw or case_id in existing or stage.get_case(case_id):
                skipped += 1
                continue
            barrier = row.get("barrier") or ""
            cmd.open_case(
                stage,
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
                    "contact_consent": row.get("consent") or None,
                },
            )
            if synthetic:
                _simulate_history(stage, case_id, row)
            opened += 1
        contacts: dict[str, dict[str, str]] = {}
        if synthetic:  # fictional names and phones, server-only; real imports keep none in this build
            contacts = {
                r["participant_id"]: {
                    "name": r.get("masked_name") or "",
                    "phone": r.get("phone") or "",
                    "data_label": LABEL,
                }
                for r in rows
                if r.get("data_label") == LABEL
            }
        n_stories = 0
        if stories:
            before = len(stage.existing_ids())
            contacts.update(play_stories(stage, lib, today=today(), now=now(), ladder=steps, skip=existing))
            n_stories = len(stage.existing_ids()) - before
        staged = [(cid, stage.load_events(cid), stage.get_case(cid)) for cid in sorted(stage.existing_ids())]
        lost = repo.create_cases(staged)
        if contacts:
            repo.put_contacts(contacts)
        out = {"opened": opened - len([c for c in lost if not c.startswith("C-DEMO-")]), "skipped": skipped + len(lost)}
        if stories:
            out["stories"] = n_stories - len([c for c in lost if c.startswith("C-DEMO-")])
        return out

    def _simulate_history(repo: CaseRepository, case_id: str, row: dict[str, str]) -> None:
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
        rep = validate_csv(await _csv_text(request), today=today())
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
        rep = validate_csv(buf.getvalue(), today=today())
        res = _open_from_rows(rep.valid_rows, SYSTEM_ACTOR, synthetic=True, stories=True)
        return {"data_label": LABEL, "disclaimer": DISCLAIMER, **res, "validation": rep.summary()}

    return app
