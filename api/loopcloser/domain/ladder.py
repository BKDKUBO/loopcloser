"""Escalation ladder (PLAN_FINAL.md section 8). Configurable; driven by a clock
that the demo can advance ("advance day").

Day 0 upload, Day 1 review, Day 2 contact, Day 4 reminder, Day 7 community health
worker, Day 10 supervisor, Day 14 unresolved review. Each step runs at most once per
case, only if its condition still holds, never on closed or paused (red-flag) cases,
and always logs an event (rule LAD-1). Reminders use the approved template only.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime

from ..store.base import CaseRepository
from . import commands as cmd
from .case import CaseView, project
from .errors import Conflict
from .events import AUTOMATION_ACTOR, SYSTEM_ACTOR, Event
from .priority import SUPPORTED_LANGUAGES
from .states import CaseState as S
from .states import is_allowed


@dataclass(frozen=True)
class Step:
    day: int
    id: str
    label: str


DEFAULT_LADDER: tuple[Step, ...] = (
    Step(0, "upload", "Result uploaded, case opened"),
    Step(1, "review", "Result reviewed by a human"),
    Step(2, "contact", "First contact attempt"),
    Step(4, "reminder", "Reminder sent (approved template)"),
    Step(7, "chw", "Community health worker follow-up"),
    Step(10, "supervisor", "Escalated to supervisor"),
    Step(14, "unresolved_review", "Unresolved case review"),
)

_BOOKED = frozenset({S.ACTION_SCHEDULED, S.VISIT_COMPLETED, S.CLOSED})


def load_ladder(raw: str | None) -> tuple[Step, ...]:
    """LADDER_JSON env, e.g. '[{"day":0,"id":"upload","label":"..."}]'. Ids must be known."""
    if not raw:
        return DEFAULT_LADDER
    steps = tuple(Step(int(s["day"]), s["id"], s.get("label", s["id"])) for s in json.loads(raw))
    known = {s.id for s in DEFAULT_LADDER}
    if any(s.id not in known for s in steps):
        raise ValueError(f"unknown ladder step; allowed: {sorted(known)}")
    return tuple(sorted(steps, key=lambda s: s.day))


def day_of(v: CaseView, today: date) -> int:
    opened = v.opened_at.date() if v.opened_at else today
    return (today - opened).days


def _needed(step: str, v: CaseView) -> bool:
    if step == "upload":
        return False  # implied by case_opened
    if step == "review":
        return v.state == S.NEW_RESULT
    if step == "contact":
        return v.contact_attempts == 0 and v.state in {S.NEW_RESULT, S.REVIEWED}
    if step == "reminder":
        return v.state in {S.REVIEWED, S.PATIENT_NOTIFIED}
    if step in {"chw", "supervisor"}:
        return v.state not in _BOOKED
    if step == "unresolved_review":
        return v.state not in {S.VISIT_COMPLETED, S.CLOSED}
    return False


needed = _needed  # public name, used by the stored query fields (indexing.py)


def status(v: CaseView, today: date, ladder: tuple[Step, ...] = DEFAULT_LADDER) -> list[dict]:
    d = day_of(v, today)

    def state(s: Step) -> str:
        if s.id in v.ladder_steps or s.id == "upload":
            return "done"
        if v.state == S.CLOSED or not _needed(s.id, v):
            return "not needed"
        return "due" if d >= s.day else "upcoming"

    def text(s: Step) -> str:
        if s.id in v.ladder_held:
            return (
                "SMS reminder not sent: held by a check (see the timeline)"
                if s.id == "reminder"
                else f"{s.label}: held"
            )
        return s.label

    return [{"day": s.day, "id": s.id, "label": text(s), "state": state(s)} for s in ladder]


def run_case(
    repo: CaseRepository,
    case_id: str,
    *,
    today: date,
    now: datetime,
    ladder: tuple[Step, ...] = DEFAULT_LADDER,
    clinic_phone: str = "the clinic",
) -> list[str]:
    actions: list[str] = []
    for step in ladder:
        v = repo.get_case(case_id)
        if v is None or v.state == S.CLOSED or v.automation_paused:
            break
        if step.id in v.ladder_steps or day_of(v, today) < step.day or not _needed(step.id, v):
            continue
        action = step.label
        held = False
        if step.id == "reminder":
            if v.phone_valid and v.contact_consent == "yes":
                lang = v.language if v.language in SUPPORTED_LANGUAGES else "en"
                cmd.record_notification(
                    repo,
                    case_id,
                    status="sent",
                    channel="sms",
                    template_id="reminder",
                    template_version="1.0.0",
                    language=lang,
                    actor=AUTOMATION_ACTOR,
                    now=now,
                )
                action = f"Reminder sent by SMS ({lang}, simulated)"
            elif v.contact_consent != "yes":
                held = True
                action = (
                    "Patient declined contact: reminder held (rule GATE-1), a coordinator decides the next step"
                    if v.contact_consent == "no"
                    else "Consent to contact not recorded: reminder held (rule GATE-1), record consent first"
                )
            else:
                held = True
                action = "No valid phone: reminder skipped, community health worker visit needed"
        elif step.id == "supervisor" and v.state != S.ESCALATED and is_allowed(v.state, S.ESCALATED):
            cmd.transition(
                repo,
                case_id,
                S.ESCALATED,
                actor=SYSTEM_ACTOR,
                now=now,
                rule_id="LAD-1",
                payload={"reason": f"Day {step.day}: not booked yet"},
            )
        cmd.record_ladder_step(repo, case_id, step=step.id, day=step.day, action=action, held=held, now=now)
        actions.append(f"{step.id}: {action}")
    return actions


class _Buffer:
    """A write buffer over the real repository. Ladder commands run against it exactly as against a
    store (same guards and events), then every change is written in bulk with commit_many."""

    def __init__(self, inner: CaseRepository, events: dict[str, list[Event]]) -> None:
        self.inner = inner
        self.indexer = None
        self._events = {k: list(v) for k, v in events.items()}
        self._base = {k: (v[-1].seq if v else 0) for k, v in self._events.items()}
        self._views: dict[str, CaseView] = {}
        self._new: dict[str, list[Event]] = {}

    def load_events(self, case_id: str) -> list[Event]:
        if case_id not in self._events:
            evs = self.inner.load_events(case_id)
            self._events[case_id], self._base[case_id] = evs, (evs[-1].seq if evs else 0)
        return list(self._events[case_id])

    def append(self, case_id: str, events: list[Event], expected_version: int, projection: CaseView) -> None:
        log = self._events.setdefault(case_id, [])
        if (log[-1].seq if log else 0) != expected_version:
            raise Conflict(f"case {case_id} changed")
        log.extend(events)
        self._new.setdefault(case_id, []).extend(events)
        self._views[case_id] = projection

    def get_case(self, case_id: str) -> CaseView | None:
        if case_id in self._views:
            return self._views[case_id]
        if case_id in self._events and self._events[case_id]:
            self._views[case_id] = project(self._events[case_id])
            return self._views[case_id]
        return self.inner.get_case(case_id)

    def pending(self) -> list[tuple[str, int, list[Event], CaseView]]:
        return [(c, self._base[c], evs, self._views[c]) for c, evs in sorted(self._new.items()) if evs]


def run_all(repo: CaseRepository, *, today: date, now: datetime, ladder: tuple[Step, ...] = DEFAULT_LADDER) -> dict:
    """Run every due ladder step. Only cases whose stored idx_ladder_due has arrived are read, their event
    logs are loaded in parallel, and all new events are written in batches (rule LAD-1 per step)."""
    started = time.monotonic()
    due = [v for v in repo.ladder_due(today.isoformat()) if v.state != S.CLOSED and not v.automation_paused]
    buf = _Buffer(repo, repo.load_events_many([v.id for v in due]))
    touched, steps = 0, 0
    for v in due:
        acts = run_case(buf, v.id, today=today, now=now, ladder=ladder)  # type: ignore[arg-type]
        if acts:
            touched += 1
            steps += len(acts)
    pending = buf.pending()
    conflicts = repo.commit_many(pending) if pending else []
    return {
        "cases_checked": len(due),
        "cases_touched": touched - len(conflicts),
        "steps_run": steps,
        "conflicts": len(conflicts),
        "as_of": today.isoformat(),
        "seconds": round(time.monotonic() - started, 2),
    }
