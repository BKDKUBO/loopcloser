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
  CLOSE-1 Closing needs an authorized human, a closure reason, evidence AND a sign-off.
  CLOSE-2 Only a supervisor (the clinical sign-off role in this build) can sign off and close.
  CLOSE-3 Structured closure evidence needs a visit date (not in the future, not before the case opened),
          a facility, and a record number.
  GATE-1  Pass/hold gates (domain/gates.py): calls and SMS are blocked while consent to contact or a valid
          phone number is missing; every contact attempt is blocked if the patient declined contact.
          Consent is recorded by a human staff member with its source, never inferred.
  PRIV-2  Downloading a case summary or audit trail is staff-only and logged as an event.
  PRIV-1  Names and phone numbers are hidden on staff screens. Revealing them is a click by a human staff
          member and is logged as an event (which fields, never the values).
  MSG-3   Official patient messages must use an approved template (id, version, language). No free text, no AI text.
  PRI-1   Only a supervisor overrides priority, with a reason code and a note.
  PRI-2   Priority cannot be lowered below Urgent while a red flag is open.
  BAR-1   Barriers come from a fixed list and each one is logged as an event.
  LAD-1   Escalation ladder steps run once each, skip paused or closed cases, and log an event.
  AI-1    AI drafts are requested by a human staff member, logged as an event, and never change the case.
  AI-2    No AI drafts while a red flag is open or after a case is closed.
  AI-3    A draft can be used only if every number and date in it was verified against the case record,
          and each draft gets exactly one Use or Discard decision, by a human.
  APPT-1  Booking from the slot picker needs a slot the simulated schedule offers (weekday, listed time, next 14
          days). Booking after the pathway deadline is allowed and noted.
  APPT-2  A simulated slot holds at most its capacity of open booked cases.
  MSG-4   A patient SMS reply (YES / RESCHED / STOP, simulated in this build) is logged as an event. YES can move a
          case to Patient notified at most (never Understanding confirmed); RESCHED moves a booked or missed visit
          to Rescheduled; STOP opts the patient out of SMS at once. Replies never book, close or clear a red flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..pathways.library import Pathway
from ..store.base import CaseRepository
from .case import CaseView, project
from .errors import GuardViolation, NotFound
from .events import SYSTEM_ACTOR, Actor, Event, EventType
from .gates import CONSENT_VALUES
from .localtime import local_date
from .priority import TIERS
from .roles import CLOSE_SIGNOFF_ROLES, Role
from .states import RED_FLAG_STATES, REQUIRED_FIELDS, CaseState, is_allowed

BARRIER_TYPES = ("transport", "cost", "work", "language", "digital", "childcare", "fear")
OVERRIDE_REASONS = (
    "duplicate",
    "already_treated",
    "worsening_symptoms",
    "completed_elsewhere",
    "data_error",
    "clinical_judgment_documented",
    "other",
)
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
    barriers: list[str] | None = None,
    source: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> CaseView:
    """source: where the result came from when it is not the CSV upload, e.g. a FHIR R4 Bundle (provenance only)."""
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
            "language": screening.get("language") or "en",
            "comorbidity": bool(screening.get("comorbidity", False)),
            "location": screening.get("location"),
            "age_band": screening.get("age_band"),
            "phone_valid": bool(screening.get("phone_valid", True)),
            "contact_consent": screening.get("contact_consent")
            if screening.get("contact_consent") in CONSENT_VALUES
            else None,
            **({"source": source} if source else {}),
        },
        rule_id=f"PATHWAY:{pathway.key}",
        fields_used=("screening_type", "result", "severity", "screened_at"),
    )
    for barrier in barriers or []:
        _check_barrier(barrier)
        b.add(EventType.BARRIER_REPORTED, actor, {"barrier": barrier, "source": "upload"}, rule_id="BAR-1")
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
        raise GuardViolation(
            "Use the close command, which needs a reason, evidence and a supervisor sign-off.", rule_id="CLOSE-1"
        )
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
    from ..templates.library import default_templates

    tpl = default_templates().get(template_id, template_version)
    if tpl is None or language not in tpl.languages:
        raise GuardViolation("Official messages must use an approved template and language.", rule_id="MSG-3")
    b = _load(repo, case_id, now)
    v = b.view
    _require_not_paused(v, actor)
    if channel == "sms" and status in {"queued", "sent"} and v.sms_opt_out:
        raise GuardViolation("The patient replied STOP. No more SMS to this patient.", rule_id="MSG-4")
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


EVIDENCE_FIELDS = ("visit_date", "facility", "record_number")
MIN_EVIDENCE_REF = 5  # a free-text evidence reference shorter than this is not evidence
_RECORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{1,39}$")


def check_evidence(evidence: dict[str, Any], *, opened: date | None, today: date) -> dict[str, str]:
    """Validate structured closure evidence (rule CLOSE-3). Returns the cleaned evidence."""
    missing = [f for f in EVIDENCE_FIELDS if not str(evidence.get(f) or "").strip()]
    if missing:
        raise GuardViolation(f"Closure evidence needs: {', '.join(missing)}.", rule_id="CLOSE-3")
    try:
        visit = date.fromisoformat(str(evidence["visit_date"]).strip()[:10])
    except ValueError:
        raise GuardViolation("Visit date must be a date (YYYY-MM-DD).", rule_id="CLOSE-3") from None
    if visit > today:
        raise GuardViolation("Visit date cannot be in the future.", rule_id="CLOSE-3")
    if opened and visit < opened:
        raise GuardViolation("Visit date cannot be before the case was opened.", rule_id="CLOSE-3")
    facility = str(evidence["facility"]).strip()
    if len(facility) > 120:
        raise GuardViolation("Facility name is too long (120 characters at most).", rule_id="CLOSE-3")
    record = str(evidence["record_number"]).strip()
    if not _RECORD_RE.match(record):
        raise GuardViolation(
            "Record number must be 2 to 40 letters, digits, spaces, dots, dashes or slashes.", rule_id="CLOSE-3"
        )
    return {"visit_date": visit.isoformat(), "facility": facility, "record_number": record}


def close_case(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    closure_reason: str,
    evidence_ref: str | None = None,
    evidence: dict[str, Any] | None = None,
    sign_off: bool = False,
    now: datetime | None = None,
    today: date | None = None,
) -> CaseView:
    """today: the clinic's local date (the API passes Manila time); defaults to the UTC date of now."""
    if not actor.is_human:
        raise GuardViolation("Cases are never closed automatically.", rule_id="CLOSE-1")
    if actor.role not in CLOSE_SIGNOFF_ROLES:
        raise GuardViolation(
            "Only a supervisor can sign off and close a case. Ask your supervisor to review the evidence.",
            rule_id="CLOSE-2",
        )
    if not closure_reason:
        raise GuardViolation("A closure reason is required.", rule_id="CLOSE-1")
    if evidence_ref is not None and len(evidence_ref.strip()) < MIN_EVIDENCE_REF:
        evidence_ref = None
    if not evidence_ref and not evidence:
        raise GuardViolation(
            "Closing needs evidence: the visit record (date, facility, record number), or for a declined or "
            "unreachable case a documented reference.",
            rule_id="CLOSE-1",
        )
    if not sign_off:
        raise GuardViolation("Closing needs evidence and a supervisor sign-off. Tick the sign-off.", rule_id="CLOSE-1")
    b = _load(repo, case_id, now)
    v = b.view
    if not is_allowed(v.state, CaseState.CLOSED):
        raise GuardViolation(f"Cannot close from {v.state.value}.", rule_id="SM-1")
    clean = None
    if evidence:
        opened = local_date(v.opened_at) if v.opened_at else None
        clean = check_evidence(evidence, opened=opened, today=today or b.now.date())
        evidence_ref = evidence_ref or (
            f"{clean['facility']}, record {clean['record_number']}, visit {clean['visit_date']}"
        )
    b.add(
        EventType.CASE_CLOSED,
        actor,
        {
            "closure_reason": closure_reason,
            "evidence_ref": evidence_ref,
            "evidence": clean,
            "signed_off_by": f"{actor.id} ({actor.role.value})",
        },
        rule_id="CLOSE-3" if clean else "CLOSE-1",
    )
    return b.commit()


def book_appointment(
    repo: CaseRepository,
    case_id: str,
    *,
    slot_id: str,
    actor: Actor,
    today: date,
    booked_in_slot: int,
    masked_participant: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> CaseView:
    """Book a simulated slot (rules APPT-1, APPT-2). Goes through the normal transition guards (SM-1, OWN-1, RF-1)."""
    from . import scheduling

    if not actor.is_human:
        raise GuardViolation("Only a person books appointments.", rule_id="AUTO-1")
    if not scheduling.is_offered(slot_id, today):
        raise GuardViolation("That slot is not offered. Pick one from the list.", rule_id="APPT-1")
    if booked_in_slot >= scheduling.CAPACITY:
        raise GuardViolation("That slot is full. Pick another time.", rule_id="APPT-2")
    v = repo.get_case(case_id)
    if v is None:
        raise NotFound(f"case {case_id} not found")
    appt = scheduling.appointment(slot_id, case_id=case_id, masked_participant=masked_participant, reason=reason)
    payload: dict[str, Any] = {"appointment": appt}
    if v.due_date and date.fromisoformat(appt["date"]) > v.due_date:
        payload["note"] = f"Booked after the pathway deadline ({v.due_date.isoformat()})"
    return transition(
        repo, case_id, CaseState.ACTION_SCHEDULED, actor=actor, payload=payload, now=now, rule_id="APPT-1"
    )


SMS_REPLY_KEYWORDS = ("YES", "RESCHED", "STOP")
# Who a simulated reply is logged as. The staff member who pressed the button is kept in the payload.
SIMULATED_PATIENT_PHONE = Actor(id="patient-sms (simulated)", role=Role.PATIENT, kind="human")


def record_sms_reply(
    repo: CaseRepository,
    case_id: str,
    *,
    keyword: str,
    entered_by: Actor,
    now: datetime | None = None,
) -> CaseView:
    """A patient SMS reply (rule MSG-4). Simulated in this build: the mock phone page posts it.

    YES moves a reviewed case to Patient notified (never Understanding confirmed, rule MSG-1) and marks a booked
    appointment as confirmed by the patient. RESCHED moves a booked or missed visit to Rescheduled, so a person
    calls to agree a new date. STOP opts the patient out of SMS at once. While a red flag is open the reply is only
    logged: a person is handling the case. Replies never book, close, or clear a red flag."""
    keyword = keyword.strip().upper()
    if keyword not in SMS_REPLY_KEYWORDS:
        raise GuardViolation("Reply must be YES, RESCHED or STOP.", rule_id="MSG-4")
    b = _load(repo, case_id, now)
    v = b.view
    if v.state == CaseState.CLOSED:
        raise GuardViolation("The case is closed.", rule_id="SM-1")
    sent = [e for e in b.existing if e.type == EventType.NOTIFICATION_STATUS and e.payload.get("status") == "sent"]
    if not any(e.payload.get("channel") == "sms" for e in sent):
        raise GuardViolation("No SMS was sent to this patient, so there is nothing to reply to.", rule_id="MSG-4")
    b.add(
        EventType.SMS_REPLY_RECEIVED,
        SIMULATED_PATIENT_PHONE,
        {"keyword": keyword, "channel": "sms", "simulated": True, "entered_by": entered_by.id},
        rule_id="MSG-4",
    )
    if v.automation_paused or v.state in RED_FLAG_STATES:
        return b.commit()
    if keyword == "YES" and v.state == CaseState.REVIEWED:
        b.add(
            EventType.STATE_CHANGED,
            SYSTEM_ACTOR,
            {"from": v.state.value, "to": CaseState.PATIENT_NOTIFIED.value, "reason": "patient replied YES by SMS"},
            rule_id="MSG-2",
        )
    elif keyword == "RESCHED" and v.state in {CaseState.ACTION_SCHEDULED, CaseState.NO_SHOW}:
        b.add(
            EventType.STATE_CHANGED,
            SYSTEM_ACTOR,
            {
                "from": v.state.value,
                "to": CaseState.RESCHEDULED.value,
                "reason": "patient replied RESCHED by SMS",
                "next_action": "Patient asked to reschedule by SMS: call to agree a new date",
            },
            rule_id="MSG-4",
        )
    return b.commit()


CONTACT_FIELDS = ("name", "phone")
STAFF_ROLES_FOR_CONTACT = frozenset({Role.WORKER, Role.COORDINATOR, Role.SUPERVISOR})


def record_contact_reveal(
    repo: CaseRepository, case_id: str, *, actor: Actor, fields: tuple[str, ...], now: datetime | None = None
) -> CaseView:
    """Log that a staff member revealed contact details (rule PRIV-1). The values are never logged."""
    if not actor.is_human or actor.role not in STAFF_ROLES_FOR_CONTACT:
        raise GuardViolation("Only care staff can reveal a name or phone number.", rule_id="PRIV-1")
    if not fields or any(f not in CONTACT_FIELDS for f in fields):
        raise GuardViolation("Pick name and/or phone.", rule_id="PRIV-1")
    b = _load(repo, case_id, now)
    b.add(EventType.CONTACT_REVEALED, actor, {"fields": list(fields)}, rule_id="PRIV-1")
    return b.commit()


def record_consent(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    consent: str,
    source: str,
    now: datetime | None = None,
) -> CaseView:
    """Record the patient's consent to be contacted (rule GATE-1). A human staff member, with where it came
    from (e.g. "in person at the home visit"). Never inferred by automation or AI."""
    if not actor.is_human or actor.role not in STAFF_ROLES_FOR_CONTACT:
        raise GuardViolation("Only care staff can record consent.", rule_id="GATE-1")
    if consent not in CONSENT_VALUES:
        raise GuardViolation("Consent must be yes or no.", rule_id="GATE-1")
    if not source.strip():
        raise GuardViolation("Say how consent was obtained (e.g. in person at the home visit).", rule_id="GATE-1")
    b = _load(repo, case_id, now)
    if b.view.state == CaseState.CLOSED:
        raise GuardViolation("The case is closed.", rule_id="SM-1")
    b.add(EventType.CONSENT_RECORDED, actor, {"consent": consent, "source": source.strip()[:200]}, rule_id="GATE-1")
    return b.commit()


EXPORT_KINDS = ("summary", "audit_csv", "audit_json")


def record_export(repo: CaseRepository, case_id: str, *, actor: Actor, kind: str, now: datetime | None = None) -> None:
    """Log a download of the case summary or audit trail (rule PRIV-2). Staff only; never changes the case."""
    if not actor.is_human or actor.role == Role.PATIENT:
        raise GuardViolation("Only staff can download case records.", rule_id="PRIV-2")
    if kind not in EXPORT_KINDS:
        raise GuardViolation("Unknown export.", rule_id="PRIV-2")
    b = _load(repo, case_id, now)
    b.add(EventType.CASE_EXPORTED, actor, {"kind": kind}, rule_id="PRIV-2")
    b.commit()


def add_note(repo: CaseRepository, case_id: str, *, actor: Actor, text: str, now: datetime | None = None) -> CaseView:
    if not text.strip():
        raise GuardViolation("Empty note.")
    b = _load(repo, case_id, now)
    b.add(EventType.NOTE_ADDED, actor, {"text": text[:2000]})
    return b.commit()


def _check_barrier(barrier: str) -> None:
    if barrier not in BARRIER_TYPES:
        raise GuardViolation(f"unknown barrier {barrier}", rule_id="BAR-1")


def report_barrier(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    barrier: str,
    source: str = "staff",
    now: datetime | None = None,
) -> CaseView:
    _check_barrier(barrier)
    b = _load(repo, case_id, now)
    if b.view.state == CaseState.CLOSED:
        raise GuardViolation("Case is closed.", rule_id="SM-1")
    b.add(EventType.BARRIER_REPORTED, actor, {"barrier": barrier, "source": source}, rule_id="BAR-1")
    return b.commit()


def resolve_barrier(
    repo: CaseRepository, case_id: str, *, actor: Actor, barrier: str, resolution: str, now: datetime | None = None
) -> CaseView:
    if not actor.is_human:
        raise GuardViolation("Only a human resolves barriers.", rule_id="AUTO-1")
    if not resolution.strip():
        raise GuardViolation("Describe how the barrier was resolved.", rule_id="BAR-1")
    b = _load(repo, case_id, now)
    if barrier not in b.view.barriers_open:
        raise GuardViolation(f"No open {barrier} barrier.", rule_id="BAR-1")
    b.add(EventType.BARRIER_RESOLVED, actor, {"barrier": barrier, "resolution": resolution[:500]}, rule_id="BAR-1")
    return b.commit()


def override_priority(
    repo: CaseRepository,
    case_id: str,
    *,
    actor: Actor,
    tier: str | None,
    reason: str,
    note: str,
    now: datetime | None = None,
) -> CaseView:
    """Set (or clear, with tier=None) a priority override. Audited as an event."""
    if not actor.is_human or actor.role != Role.SUPERVISOR:
        raise GuardViolation("Only a supervisor can override priority.", rule_id="PRI-1")
    if tier is not None and tier not in TIERS:
        raise GuardViolation(f"unknown tier {tier}", rule_id="PRI-1")
    if reason not in OVERRIDE_REASONS or not note.strip():
        raise GuardViolation("Pick a reason and add a note.", rule_id="PRI-1")
    b = _load(repo, case_id, now)
    v = b.view
    if v.state == CaseState.CLOSED:
        raise GuardViolation("Case is closed.", rule_id="SM-1")
    if v.red_flag_open and tier not in ("urgent", None):
        raise GuardViolation("Cannot lower priority while a red flag is open.", rule_id="PRI-2")
    if v.red_flag_open and tier is None:
        raise GuardViolation("Cannot clear an override while a red flag is open.", rule_id="PRI-2")
    b.add(
        EventType.PRIORITY_OVERRIDDEN,
        actor,
        {"tier": tier, "reason": reason, "note": note[:1000], "previous": v.priority_override},
        rule_id="PRI-1",
    )
    return b.commit()


def record_ladder_step(
    repo: CaseRepository,
    case_id: str,
    *,
    step: str,
    day: int,
    action: str,
    held: bool = False,
    now: datetime | None = None,
) -> CaseView:
    """held: the step ran but did not contact the patient (no valid phone, or a consent gate on Hold)."""
    b = _load(repo, case_id, now)
    payload: dict[str, Any] = {"step": step, "day": day, "action": action}
    if held:
        payload["held"] = True
    b.add(EventType.LADDER_STEP, SYSTEM_ACTOR, payload, rule_id="LAD-1")
    return b.commit()


def rebuild(repo: CaseRepository, case_id: str) -> CaseView:
    """Rebuild a projection from events (used by tests and the admin endpoint)."""
    events = repo.load_events(case_id)
    if not events:
        raise NotFound(f"case {case_id} not found")
    return project(events)


AI_DECISIONS = ("use", "discard")
STAFF_ROLES_FOR_AI = frozenset({Role.WORKER, Role.COORDINATOR, Role.SUPERVISOR})


def _check_ai_actor(actor: Actor) -> None:
    if not actor.is_human or actor.role not in STAFF_ROLES_FOR_AI:
        raise GuardViolation("Only staff can request or decide on AI drafts.", rule_id="AI-1")


def check_ai_draft_allowed(repo: CaseRepository, case_id: str, *, actor: Actor) -> CaseView:
    """Call before asking the model, so a refused request costs nothing."""
    _check_ai_actor(actor)
    v = rebuild(repo, case_id)
    if v.state == CaseState.CLOSED:
        raise GuardViolation("Case is closed.", rule_id="AI-2")
    if v.red_flag_open or v.state in RED_FLAG_STATES:
        raise GuardViolation("No AI drafts while a red flag is open. A human handles it.", rule_id="AI-2")
    return v


def record_ai_draft(
    repo: CaseRepository, case_id: str, *, actor: Actor, payload: dict[str, Any], now: datetime | None = None
) -> tuple[CaseView, int]:
    """Log an AI draft. Returns the projection (unchanged apart from its version) and the draft's event seq."""
    _check_ai_actor(actor)
    b = _load(repo, case_id, now)
    b.add(EventType.AI_DRAFT_CREATED, actor, payload, rule_id="AI-1")
    seq = b.new[-1].seq
    return b.commit(), seq


def decide_ai_draft(
    repo: CaseRepository, case_id: str, *, actor: Actor, draft_seq: int, decision: str, now: datetime | None = None
) -> CaseView:
    _check_ai_actor(actor)
    if decision not in AI_DECISIONS:
        raise GuardViolation("Decision must be use or discard.", rule_id="AI-3")
    b = _load(repo, case_id, now)
    draft = next((e for e in b.existing if e.seq == draft_seq and e.type == EventType.AI_DRAFT_CREATED), None)
    if draft is None:
        raise NotFound(f"draft {draft_seq} not found on case {case_id}")
    if any(e.type == EventType.AI_DRAFT_DECISION and e.payload.get("draft_seq") == draft_seq for e in b.existing):
        raise GuardViolation("This draft already has a decision.", rule_id="AI-3")
    if decision == "use" and not draft.payload.get("verified"):
        raise GuardViolation(
            "This draft mentions numbers or dates that are not in the case record. Discard it.", rule_id="AI-3"
        )
    b.add(EventType.AI_DRAFT_DECISION, actor, {"draft_seq": draft_seq, "decision": decision}, rule_id="AI-3")
    return b.commit()


def latest_ai_draft(repo: CaseRepository, case_id: str) -> dict[str, Any] | None:
    """The newest call-prep draft and its decision, for the case page."""
    events = repo.load_events(case_id)
    drafts = [e for e in events if e.type == EventType.AI_DRAFT_CREATED]
    if not drafts:
        return None
    d = drafts[-1]
    decision = next(
        (e for e in events if e.type == EventType.AI_DRAFT_DECISION and e.payload.get("draft_seq") == d.seq), None
    )
    return {
        "draft_seq": d.seq,
        "at": d.at.isoformat(),
        "by": d.actor.id,
        **d.payload,
        "decision": decision.payload["decision"] if decision else None,
        "decided_by": decision.actor.id if decision else None,
    }
