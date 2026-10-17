"""Case state machine for the screening-to-care loop.

Main path, exception states and red-flag states come from PLAN_FINAL.md section 3.
State is never stored as the source of truth. It is derived from the event log
(see events.py and case.py). This module only says which moves are legal.
"""

from __future__ import annotations

from enum import StrEnum


class CaseState(StrEnum):
    # Main path
    NEW_RESULT = "new_result"
    REVIEWED = "reviewed"
    PATIENT_NOTIFIED = "patient_notified"
    UNDERSTANDING_CONFIRMED = "understanding_confirmed"
    ACTION_SCHEDULED = "action_scheduled"
    VISIT_COMPLETED = "visit_completed"
    CLOSED = "closed"
    # Exception states
    UNABLE_TO_REACH = "unable_to_reach"
    DECLINED = "declined"
    RESCHEDULED = "rescheduled"
    REFERRAL_REJECTED = "referral_rejected"
    NO_SHOW = "no_show"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    ESCALATED = "escalated"
    # Red-flag states
    RED_FLAG_REPORTED = "red_flag_reported"
    AUTOMATION_PAUSED = "automation_paused"
    HUMAN_TASK_OPEN = "human_task_open"
    CLINICIAN_CONTACTED = "clinician_contacted"
    RESOLVED_BY_HUMAN = "resolved_by_human"


MAIN_PATH: tuple[CaseState, ...] = (
    CaseState.NEW_RESULT,
    CaseState.REVIEWED,
    CaseState.PATIENT_NOTIFIED,
    CaseState.UNDERSTANDING_CONFIRMED,
    CaseState.ACTION_SCHEDULED,
    CaseState.VISIT_COMPLETED,
    CaseState.CLOSED,
)

EXCEPTION_STATES: frozenset[CaseState] = frozenset(
    {
        CaseState.UNABLE_TO_REACH,
        CaseState.DECLINED,
        CaseState.RESCHEDULED,
        CaseState.REFERRAL_REJECTED,
        CaseState.NO_SHOW,
        CaseState.AWAITING_HUMAN_REVIEW,
        CaseState.ESCALATED,
    }
)

RED_FLAG_STATES: frozenset[CaseState] = frozenset(
    {
        CaseState.RED_FLAG_REPORTED,
        CaseState.AUTOMATION_PAUSED,
        CaseState.HUMAN_TASK_OPEN,
        CaseState.CLINICIAN_CONTACTED,
        CaseState.RESOLVED_BY_HUMAN,
    }
)

TERMINAL_STATES: frozenset[CaseState] = frozenset({CaseState.CLOSED})

# Exception states need extra fields on the transition payload.
REQUIRED_FIELDS: dict[CaseState, tuple[str, ...]] = {
    CaseState.UNABLE_TO_REACH: ("reason", "escalation_date"),
    CaseState.DECLINED: ("reason",),
    CaseState.RESCHEDULED: ("reason",),
    CaseState.REFERRAL_REJECTED: ("reason",),
    CaseState.NO_SHOW: (),
    CaseState.AWAITING_HUMAN_REVIEW: ("reason",),
    CaseState.ESCALATED: ("reason",),
}

_OPEN_MAIN = frozenset(MAIN_PATH) - TERMINAL_STATES

# Explicit adjacency for the main path plus re-entry from exception states.
_ALLOWED: dict[CaseState, frozenset[CaseState]] = {
    CaseState.NEW_RESULT: frozenset({CaseState.REVIEWED}),
    CaseState.REVIEWED: frozenset({CaseState.PATIENT_NOTIFIED}),
    CaseState.PATIENT_NOTIFIED: frozenset({CaseState.UNDERSTANDING_CONFIRMED}),
    CaseState.UNDERSTANDING_CONFIRMED: frozenset({CaseState.ACTION_SCHEDULED}),
    CaseState.ACTION_SCHEDULED: frozenset({CaseState.VISIT_COMPLETED}),
    CaseState.VISIT_COMPLETED: frozenset({CaseState.CLOSED}),
    # Exception states can re-enter the main path at the step they block.
    CaseState.UNABLE_TO_REACH: frozenset({CaseState.PATIENT_NOTIFIED, CaseState.CLOSED}),
    CaseState.DECLINED: frozenset({CaseState.PATIENT_NOTIFIED, CaseState.ACTION_SCHEDULED, CaseState.CLOSED}),
    CaseState.RESCHEDULED: frozenset({CaseState.ACTION_SCHEDULED}),
    CaseState.REFERRAL_REJECTED: frozenset({CaseState.REVIEWED, CaseState.ACTION_SCHEDULED, CaseState.CLOSED}),
    CaseState.NO_SHOW: frozenset({CaseState.ACTION_SCHEDULED, CaseState.CLOSED}),
    CaseState.AWAITING_HUMAN_REVIEW: frozenset(_OPEN_MAIN),
    CaseState.ESCALATED: frozenset(_OPEN_MAIN | {CaseState.CLOSED}),
    # Red-flag flow. Entry happens through the dedicated red-flag command.
    CaseState.RED_FLAG_REPORTED: frozenset({CaseState.AUTOMATION_PAUSED}),
    CaseState.AUTOMATION_PAUSED: frozenset({CaseState.HUMAN_TASK_OPEN}),
    CaseState.HUMAN_TASK_OPEN: frozenset({CaseState.CLINICIAN_CONTACTED, CaseState.RESOLVED_BY_HUMAN}),
    CaseState.CLINICIAN_CONTACTED: frozenset({CaseState.RESOLVED_BY_HUMAN}),
    CaseState.RESOLVED_BY_HUMAN: frozenset(_OPEN_MAIN | {CaseState.CLOSED}),
    CaseState.CLOSED: frozenset(),
}

_S = CaseState
# Where each exception state can be entered from. Human review and escalation
# can happen from any open, non-red-flag state.
_EXCEPTION_SOURCES: dict[CaseState, frozenset[CaseState]] = {
    _S.UNABLE_TO_REACH: frozenset(
        {_S.REVIEWED, _S.PATIENT_NOTIFIED, _S.UNDERSTANDING_CONFIRMED, _S.ACTION_SCHEDULED, _S.NO_SHOW, _S.RESCHEDULED}
    ),
    _S.DECLINED: frozenset(
        {_S.PATIENT_NOTIFIED, _S.UNDERSTANDING_CONFIRMED, _S.ACTION_SCHEDULED, _S.RESCHEDULED, _S.NO_SHOW}
    ),
    _S.RESCHEDULED: frozenset({_S.ACTION_SCHEDULED, _S.NO_SHOW}),
    _S.REFERRAL_REJECTED: frozenset({_S.ACTION_SCHEDULED}),
    _S.NO_SHOW: frozenset({_S.ACTION_SCHEDULED, _S.RESCHEDULED}),
}
_ANYWHERE_OPEN = frozenset(CaseState) - TERMINAL_STATES - RED_FLAG_STATES
_EXCEPTION_SOURCES[_S.AWAITING_HUMAN_REVIEW] = _ANYWHERE_OPEN
_EXCEPTION_SOURCES[_S.ESCALATED] = _ANYWHERE_OPEN


def allowed_targets(current: CaseState) -> frozenset[CaseState]:
    targets = set(_ALLOWED[current])
    for target, sources in _EXCEPTION_SOURCES.items():
        if current in sources and target != current:
            targets.add(target)
    return frozenset(targets)


def is_allowed(current: CaseState, target: CaseState) -> bool:
    return target in allowed_targets(current)


def is_open(state: CaseState) -> bool:
    return state not in TERMINAL_STATES
