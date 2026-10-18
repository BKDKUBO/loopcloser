"""Escalation ladder (PLAN_FINAL.md section 8). Configurable; driven by a clock
that the demo can advance ("advance day").

Day 0 upload, Day 1 review, Day 2 contact, Day 4 reminder, Day 7 community health
worker, Day 10 supervisor, Day 14 unresolved review. Each step runs at most once per
case, only if its condition still holds, never on closed or paused (red-flag) cases,
and always logs an event (rule LAD-1). Reminders use the approved template only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime

from ..store.base import CaseRepository
from . import commands as cmd
from .case import CaseView
from .events import AUTOMATION_ACTOR, SYSTEM_ACTOR
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


def status(v: CaseView, today: date, ladder: tuple[Step, ...] = DEFAULT_LADDER) -> list[dict]:
    d = day_of(v, today)

    def state(s: Step) -> str:
        if s.id in v.ladder_steps or s.id == "upload":
            return "done"
        if v.state == S.CLOSED or not _needed(s.id, v):
            return "not needed"
        return "due" if d >= s.day else "upcoming"

    return [{"day": s.day, "id": s.id, "label": s.label, "state": state(s)} for s in ladder]


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
        if step.id == "reminder":
            if v.phone_valid:
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
            else:
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
        cmd.record_ladder_step(repo, case_id, step=step.id, day=step.day, action=action, now=now)
        actions.append(f"{step.id}: {action}")
    return actions


def run_all(repo: CaseRepository, *, today: date, now: datetime, ladder: tuple[Step, ...] = DEFAULT_LADDER) -> dict:
    touched, steps = 0, 0
    for v in repo.list_cases():
        if v.state == S.CLOSED or v.automation_paused:
            continue
        acts = run_case(repo, v.id, today=today, now=now, ladder=ladder)
        if acts:
            touched += 1
            steps += len(acts)
    return {"cases_touched": touched, "steps_run": steps, "as_of": today.isoformat()}
