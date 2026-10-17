"""Commands: the only way to change a case. Each command checks guard rules,
appends events, and re-projects the case from the full event log.

Guard rule ids (also listed in docs/guard-rules.md):
  SM-1    Transition must be allowed by the state machine.
  SM-2    Exception states need their required fields (e.g. reason, escalation date).
  AUTO-1  Non-human actors can only escalate or request human review.
  MSG-1   Understanding is confirmed only by the check or by staff, never by a message.
  MSG-2   A delivered/opened message moves a case to Patient notified at most.
  OWN-1   Urgent cases need a human owner before moving past Reviewed.
  RF-1    While automation is paused (red flag), automation and system actors cannot act.
  RF-2    Only a human can move a case out of the red-flag states or resume automation.
  ESC-1   Escalate after N failed contact attempts (configurable).
  CLOSE-1 Closing needs an authorized human, a closure reason, and evidence or sign-off.
  CLOSE-2 Only coordinator or supervisor can close or sign off.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..pathways.library import Pathway
from ..store.base import CaseRepository
from .case import CaseView, project
from .errors import GuardViolation, NotFound
from .events import SYSTEM_ACTOR, Actor, Event, EventType
from .roles import CLOSE_SIGNOFF_ROLES, Role
from .states import RED_FLAG_STATES, REQUIRED_FIELDS, CaseState, is_allowed

NON_HUMAN_TARGETS = frozenset({CaseState.ESCALATED, CaseState.AWAITING_HUMAN_REVIEW})
UNDERSTANDING_SOURCES = frozenset({"understanding_check", "staff_confirmed"})


@dataclass(frozen=True)
class Settings:
    escalate_after_failed_contacts: int = 3
    red_flag_task_due_hours: int = 24


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


class _Batch:
    """Collects new events for one case and applies them to a running projection."""

    def __init__(self, repo: CaseRepository, case_id: str, now: datetime, existing: list[Event]) -> None:
        self.repo, self.case_id, self.now = repo, case_id, now
        self.existing = existing
        self.base_version = existing[-1].seq if existing else 0
        self.new: list[Event] = []

    @property
    def view(self) -> CaseView:
        return project(self.existing + self.new)

    def add(
        self,
        etype: EventType,
        actor: Actor,
        payload: dict[str, Any] | None = None,
        *,
        rule_id: str | None = None,
        fields_used: tuple[str, ...] = (),
    ) -> None:
        seq = self.base_version + len(self.new) + 1
        self.new.append(
            Event(
                id=Event.make_id(self.case_id, seq),
                case_id=self.case_id,
                seq=seq,
                type=etype,
                at=self.now,
                actor=actor,
                rule_id=rule_id,
                fields_used=fields_used,
                payload=payload or {},
            )
        )

    def commit(self) -> CaseView:
        view = self.view
        self.repo.append(self.case_id, self.new, self.base_version, view)
        return view


def _load(repo: CaseRepository, case_id: str, now: datetime | None) -> _Batch:
    events = repo.load_events(case_id)
    if not events:
        raise NotFound(f"case {case_id} not found")
    return _Batch(repo, case_id, _now(now), events)


def _require_not_paused(view: CaseView, actor: Actor) -> None:
    if view.automation_paused and not actor.is_human:
        raise GuardViolation("Automation is paused because of a red flag. A human must act.", rule_id="RF-1")


# ---------------------------------------------------------------- commands


def open_case(
    repo: CaseRepository,
    *,
    case_id: str,
    screening: dict[str, Any],
    pathway: Pathway,
    actor: Actor,
    owner: str | None = None,
    patient_uid: str | None = None,
    synthetic: bool = False,
    now: datetime | None = None,
) -> CaseView:
    if repo.load_events(case_id):
        raise GuardViolation(f"case {case_id} already exists", rule_id="SM-1")
    t = _now(now)
    screened_at = date.fromisoformat(str(screening["screened_at"])[:10])
    due = screened_at + timedelta(days=pathway.default_deadline_days)
    severity = screening["severity"]
    red_flag = bool(screening.get("red_flag"))
    urgent = severity == "critical" or red_flag or pathway.red_flag_route
    b = _Batch(repo, case_id, t, [])
    b.add(
        EventType.CASE_OPENED,
        actor,
        {
            "participant_id": screening["participant_id"],
            "screening_id": screening["screening_id"],
            "screening_type": screening["screening_type"],
            "result": screening.get("result"),
            "severity": severity,
            "pathway_id": pathway.id,
            "pathway_version": pathway.version,
            "pathway_signoff_status": pathway.signoff_status,
            "next_action": pathway.next_action,
            "due_date": due.isoformat(),
            "deadline_label": pathway.deadline_label,
            "clinical_urgency": "urgent" if urgent else "standard",
            "owner": owner,
            "patient_uid": patient_uid,
            "synthetic": synthetic,
            "data_label": "SIMULATED" if synthetic else None,
        },
        rule_id=f"PATHWAY:{pathway.key}",
        fields_used=("screening_type", "result", "severity", "screened_at"),
    )
    if red_flag or pathway.red_flag_route:
        _red_flag_events(b, actor, source="upload" if red_flag else "pathway", code="flagged_at_intake")
    return b.commit()


def assign(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    owner: str | None = None,
    backup_owner: str | None = None,
    clinician_reviewer: str | None = None,
    now: datetime | None = None,
) -> CaseView:
    if not actor.is_human:
        raise GuardViolation("Only a human can assign owners.", rule_id="AUTO-1")
    b = _load(repo, case_id, now)
    payload = {
        k: v
        for k, v in {"owner": owner, "backup_owner": backup_owner, "clinician_reviewer": clinician_reviewer}.items()
        if v is not None
    }
    if not payload:
        raise GuardViolation("Nothing to assign.")
    b.add(EventType.OWNER_ASSIGNED, actor, payload)
    return b.commit()


def transition(
    repo: CaseRepository,
    case_id: str,
    target: CaseState,
    *,
    actor: Actor,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
    rule_id: str | None = None,
) -> CaseView:
    payload = dict(payload or {})
    b = _load(repo, case_id, now)
    v = b.view
    _check_transition(v, target, actor, payload)
    b.add(EventType.STATE_CHANGED, actor, {"from": v.state.value, "to": target.value, **payload}, rule_id=rule_id)
    return b.commit()


def _check_transition(v: CaseView, target: CaseState, actor: Actor, payload: dict[str, Any]) -> None:
    if target == CaseState.CLOSED:
        raise GuardViolation("Use the close command, which needs a reason and evidence or sign-off.", rule_id="CLOSE-1")
    if target in RED_FLAG_STATES and v.state not in RED_FLAG_STATES:
        raise GuardViolation("Use the red-flag command to enter the red-flag flow.", rule_id="SM-1")
    if not is_allowed(v.state, target):
        raise GuardViolation(f"Cannot move from {v.state.value} to {target.value}.", rule_id="SM-1")
    _require_not_paused(v, actor)
    if not actor.is_human and target not in NON_HUMAN_TARGETS:
        raise GuardViolation("Automation can only escalate or request human review.", rule_id="AUTO-1")
    if v.state in RED_FLAG_STATES and not actor.is_human:
        raise GuardViolation("Only a human can move a case through the red-flag flow.", rule_id="RF-2")
    missing = [f for f in REQUIRED_FIELDS.get(target, ()) if not payload.get(f)]
    if missing:
        raise GuardViolation(f"{target.value} needs: {', '.join(missing)}", rule_id="SM-2")
    if target == CaseState.UNDERSTANDING_CONFIRMED and payload.get("source") not in UNDERSTANDING_SOURCES:
        raise GuardViolation(
            "Understanding must come from the understanding check or staff, not a message.", rule_id="MSG-1"
        )
    past_review = target not in {CaseState.REVIEWED, CaseState.AWAITING_HUMAN_REVIEW, CaseState.ESCALATED}
    if v.clinical_urgency == "urgent" and not v.owner and past_review:
        raise GuardViolation("Urgent cases need a human owner first.", rule_id="OWN-1")


def record_notification(
    repo: CaseRepository,
    case_id: str,
    *,
    status: str,
    channel: str,
    template_id: str,
    template_version: str,
    language: str,
    actor: Actor,
    now: datetime | None = None,
) -> CaseView:
    if status not in {"queued", "sent", "delivered", "opened", "failed"}:
        raise GuardViolation(f"unknown notification status {status}")
    b = _load(repo, case_id, now)
    v = b.view
    _require_not_paused(v, actor)
    b.add(
        EventType.NOTIFICATION_STATUS,
        actor,
        {
            "status": status,
            "channel": channel,
            "template_id": template_id,
            "template_version": template_version,
            "language": language,
            "simulated": True,
        },
    )
    if status in {"delivered", "opened"} and v.state == CaseState.REVIEWED:
        b.add(
            EventType.STATE_CHANGED,
            SYSTEM_ACTOR,
            {"from": v.state.value, "to": CaseState.PATIENT_NOTIFIED.value, "reason": f"message {status}"},
            rule_id="MSG-2",
        )
    return b.commit()


def log_contact_attempt(
    repo: CaseRepository,
    case_id: str,
    *,
    channel: str,
    result: str,
    actor: Actor,
    settings: Settings = Settings(),
    now: datetime | None = None,
) -> CaseView:
    if result not in {"reached", "no_answer", "invalid_number", "busy", "left_message"}:
        raise GuardViolation(f"unknown contact result {result}")
    b = _load(repo, case_id, now)
    _require_not_paused(b.view, actor)
    b.add(EventType.CONTACT_ATTEMPT, actor, {"channel": channel, "result": result})
    v = b.view
    if (
        result != "reached"
        and v.failed_contact_attempts >= settings.escalate_after_failed_contacts
        and v.state != CaseState.ESCALATED
        and is_allowed(v.state, CaseState.ESCALATED)
        and not v.automation_paused
    ):
        b.add(
            EventType.STATE_CHANGED,
            SYSTEM_ACTOR,
            {
                "from": v.state.value,
                "to": CaseState.ESCALATED.value,
                "reason": f"{v.failed_contact_attempts} failed contact attempts",
            },
            rule_id="ESC-1",
            fields_used=("failed_contact_attempts",),
        )
    return b.commit()


def _red_flag_events(b: _Batch, actor: Actor, *, source: str, code: str) -> None:
    v = b.view
    already = v.state in RED_FLAG_STATES
    b.add(
        EventType.RED_FLAG_REPORTED,
        actor,
        {"source": source, "code": code, "state_change": not already},
        rule_id="RF-1",
    )
    if already:
        return
    b.add(
        EventType.STATE_CHANGED,
        SYSTEM_ACTOR,
        {
            "from": CaseState.RED_FLAG_REPORTED.value,
            "to": CaseState.AUTOMATION_PAUSED.value,
            "reason": "red flag stops automation",
        },
        rule_id="RF-1",
    )
    due = b.now + timedelta(hours=Settings().red_flag_task_due_hours)
    b.add(
        EventType.STATE_CHANGED,
        SYSTEM_ACTOR,
        {
            "from": CaseState.AUTOMATION_PAUSED.value,
            "to": CaseState.HUMAN_TASK_OPEN.value,
            "reason": "human task created",
            "task": {"kind": "red_flag_review", "owner": v.owner or "supervisor-queue", "due": due.isoformat()},
            "next_action": "Human red-flag review. Patient sees emergency guidance.",
        },
        rule_id="RF-1",
    )


def report_red_flag(
    repo: CaseRepository, case_id: str, *, actor: Actor, source: str, code: str, now: datetime | None = None
) -> CaseView:
    """Anyone (patient, staff, importer) can report. Automation stops immediately."""
    b = _load(repo, case_id, now)
    if b.view.state == CaseState.CLOSED:
        raise GuardViolation("Case is closed. Open a new case for new symptoms.", rule_id="SM-1")
    _red_flag_events(b, actor, source=source, code=code)
    return b.commit()


def resume_automation(
    repo: CaseRepository, case_id: str, *, actor: Actor, reason: str, now: datetime | None = None
) -> CaseView:
    if not actor.is_human or actor.role != Role.SUPERVISOR:
        raise GuardViolation("Only a supervisor can resume automation.", rule_id="RF-2")
    b = _load(repo, case_id, now)
    v = b.view
    if not v.automation_paused:
        raise GuardViolation("Automation is not paused.")
    if v.red_flag_open:
        raise GuardViolation("Resolve the red flag first.", rule_id="RF-2")
    if not reason:
        raise GuardViolation("A reason is required.", rule_id="RF-2")
    b.add(EventType.AUTOMATION_RESUMED, actor, {"reason": reason}, rule_id="RF-2")
    return b.commit()


def close_case(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    closure_reason: str,
    evidence_ref: str | None = None,
    sign_off: bool = False,
    now: datetime | None = None,
) -> CaseView:
    if not actor.is_human:
        raise GuardViolation("Cases are never closed automatically.", rule_id="CLOSE-1")
    if actor.role not in CLOSE_SIGNOFF_ROLES:
        raise GuardViolation("Only a coordinator or supervisor can close a case.", rule_id="CLOSE-2")
    if not closure_reason:
        raise GuardViolation("A closure reason is required.", rule_id="CLOSE-1")
    if not evidence_ref and not sign_off:
        raise GuardViolation("Closing needs evidence (visit record or upload) or a sign-off.", rule_id="CLOSE-1")
    b = _load(repo, case_id, now)
    v = b.view
    if not is_allowed(v.state, CaseState.CLOSED):
        raise GuardViolation(f"Cannot close from {v.state.value}.", rule_id="SM-1")
    b.add(
        EventType.CASE_CLOSED,
        actor,
        {
            "closure_reason": closure_reason,
            "evidence_ref": evidence_ref,
            "signed_off_by": f"{actor.id} ({actor.role.value})" if sign_off else None,
        },
        rule_id="CLOSE-1",
    )
    return b.commit()


def add_note(repo: CaseRepository, case_id: str, *, actor: Actor, text: str, now: datetime | None = None) -> CaseView:
    if not text.strip():
        raise GuardViolation("Empty note.")
    b = _load(repo, case_id, now)
    b.add(EventType.NOTE_ADDED, actor, {"text": text[:2000]})
    return b.commit()


def rebuild(repo: CaseRepository, case_id: str) -> CaseView:
    """Rebuild a projection from events (used by tests and the admin endpoint)."""
    events = repo.load_events(case_id)
    if not events:
        raise NotFound(f"case {case_id} not found")
    return project(events)
