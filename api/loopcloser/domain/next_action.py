"""One recommended action per case (Today view and case panel). Deterministic."""

from __future__ import annotations

from typing import Any

from .case import CaseView
from .states import RED_FLAG_STATES
from .states import CaseState as S

_BY_STATE: dict[S, tuple[str, str, S | None]] = {
    S.NEW_RESULT: ("Review the result", "transition", S.REVIEWED),
    S.REVIEWED: ("Contact the patient", "contact", None),
    S.PATIENT_NOTIFIED: ("Confirm the patient understands the next step", "transition", S.UNDERSTANDING_CONFIRMED),
    S.UNDERSTANDING_CONFIRMED: ("Book the appointment", "transition", S.ACTION_SCHEDULED),
    S.ACTION_SCHEDULED: ("Record the visit", "transition", S.VISIT_COMPLETED),
    S.VISIT_COMPLETED: ("Close with evidence", "close", S.CLOSED),
    S.UNABLE_TO_REACH: ("Try another channel or send a community health worker", "contact", None),
    S.DECLINED: ("Record the decline reason, offer help, or close with sign-off", "close", S.CLOSED),
    S.RESCHEDULED: ("Book the new appointment", "transition", S.ACTION_SCHEDULED),
    S.REFERRAL_REJECTED: ("Find another referral site", "transition", S.ACTION_SCHEDULED),
    S.NO_SHOW: ("Call to rebook", "contact", None),
    S.AWAITING_HUMAN_REVIEW: ("Review and decide the next step", "transition", None),
    S.ESCALATED: ("Supervisor: decide the next step", "transition", None),
    S.CLOSED: ("No action. Case closed.", "none", None),
}


def recommend(v: CaseView) -> dict[str, Any]:
    if v.state in RED_FLAG_STATES:
        target = {S.HUMAN_TASK_OPEN: S.CLINICIAN_CONTACTED, S.CLINICIAN_CONTACTED: S.RESOLVED_BY_HUMAN}.get(v.state)
        label = "Human red-flag review. Patient sees emergency guidance."
        if v.state == S.RESOLVED_BY_HUMAN:
            label = "Red flag resolved. Choose the next step; a supervisor can resume automation."
        return {"label": label, "kind": "transition", "target": target.value if target else None}
    if not v.owner and v.state != S.CLOSED:
        return {"label": "Assign an owner", "kind": "assign", "target": None}
    if v.state != S.CLOSED and v.contact_consent == "no":
        return {
            "label": "Patient declined contact: a coordinator decides the next step",
            "kind": "consent",
            "target": None,
        }
    if v.state != S.CLOSED and v.contact_consent is None and v.state not in {S.NEW_RESULT}:
        return {"label": "Record consent to contact before calling or texting", "kind": "consent", "target": None}
    if v.barriers_open:
        return {"label": f"Resolve barrier: {', '.join(v.barriers_open)}", "kind": "barrier", "target": None}
    label, kind, target = _BY_STATE[v.state]
    return {"label": label, "kind": kind, "target": target.value if target else None}


# Plain statuses for staff screens (the full state is still shown in the timeline).
PLAIN_STATUSES: dict[str, str] = {
    "to_contact": "To contact",
    "booked": "Booked",
    "needs_review": "Needs review",
    "done": "Done",
}
_REVIEW = frozenset({S.ESCALATED, S.AWAITING_HUMAN_REVIEW}) | RED_FLAG_STATES
_DONE = frozenset({S.VISIT_COMPLETED, S.CLOSED})
LOST_AFTER_FAILED_CONTACTS = 3


def plain_status(v: CaseView) -> str:
    """One of four plain statuses. Deterministic, derived from the case state."""
    if v.state in _DONE:
        return "done"
    if v.red_flag_open or v.state in _REVIEW:
        return "needs_review"
    if v.state == S.ACTION_SCHEDULED:
        return "booked"
    return "to_contact"


def lost_contact(v: CaseView) -> bool:
    """Open case where the patient cannot be reached: marked unable to reach, or 3+ failed contact
    attempts with no successful one."""
    if v.state in _DONE:
        return False
    return v.state == S.UNABLE_TO_REACH or (
        v.failed_contact_attempts >= LOST_AFTER_FAILED_CONTACTS and v.reached_contacts == 0
    )
