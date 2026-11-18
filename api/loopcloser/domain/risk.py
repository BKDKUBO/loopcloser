"""Attendance (drop-off) risk: fixed rules, points and plain-language help. Rule ids RISK-*.

Same style as priority.py, computed at read time. These are rules the team chose, not a prediction: no
probabilities or percentages are shown, and the thresholds are not clinically validated. Risk never changes the
case state, never changes the published priority tier or score, and never contacts anyone. It only shows staff
which open cases have signs of dropping off, and an administrative suggestion for each sign.

Declined contact consent is not scored (it is the patient's choice, not a barrier). Closed, visit-done and red-flag
cases are excluded (a red flag is already handled by a person).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .case import CaseView
from .states import RED_FLAG_STATES
from .states import CaseState as S

WATCH_AT = 3
HIGH_AT = 6
BARRIER_MAX = 4
BARRIER_HELP = {
    "transport": "Ask how they will get there; arrange a ride or transport help, if the program has one.",
    "cost": "Check what the visit will cost the patient and connect them to the social worker.",
    "work": "Offer a time outside working hours, if the clinic has one.",
    "language": "Use a navigator who speaks the patient's language.",
    "digital": "Call or visit instead of relying on SMS.",
    "childcare": "Offer a time when childcare is easier, or ask whether a family member can help.",
    "fear": "A trusted community health worker can talk it through; a clinician answers medical questions.",
}
_NOT_BOOKED = frozenset(
    {
        S.NEW_RESULT,
        S.REVIEWED,
        S.PATIENT_NOTIFIED,
        S.UNDERSTANDING_CONFIRMED,
        S.UNABLE_TO_REACH,
        S.RESCHEDULED,
        S.NO_SHOW,
        S.AWAITING_HUMAN_REVIEW,
        S.ESCALATED,
        S.REFERRAL_REJECTED,
    }
)
_EXCLUDED = frozenset({S.CLOSED, S.VISIT_COMPLETED, S.DECLINED}) | RED_FLAG_STATES


@dataclass(frozen=True)
class Rule:
    id: str
    points: int
    label: str
    help: str


RULES: tuple[Rule, ...] = (
    Rule(
        "RISK-FAILED",
        2,
        "2 or more failed contact attempts, nobody reached",
        "Try another channel or send a community health worker.",
    ),
    Rule("RISK-NOSHOW", 3, "Missed an appointment", "Call to find out why before rebooking."),
    Rule("RISK-RESCHED", 1, "Rescheduled 2 or more times", "Ask what would make the next date work."),
    Rule("RISK-BARRIER", 2, "Open barrier (2 points each, 4 at most)", "See the suggestion for each barrier."),
    Rule("RISK-NO-PHONE", 2, "No valid phone on file", "Update the number or plan a home visit."),
    Rule("RISK-SILENT", 1, "Reminder SMS went out, nobody reached yet", "Follow up by call or visit."),
    Rule("RISK-DEADLINE", 2, "Deadline within 7 days or passed, not booked", "Book now; ask about barriers first."),
    Rule(
        "RISK-APPT-SOON",
        2,
        "Appointment within 3 days and a barrier is open or nobody was reached",
        "Confirm the appointment and sort out the barrier before the day.",
    ),
)
_BY_ID = {r.id: r for r in RULES}


def _reason(
    rule_id: str, detail: str | None = None, points: int | None = None, help: str | None = None
) -> dict[str, Any]:
    r = _BY_ID[rule_id]
    return {
        "rule_id": r.id,
        "points": r.points if points is None else points,
        "label": r.label,
        "detail": detail,
        "help": help or r.help,
    }


def _days(days: int, past: str, future: str) -> str:
    if days == 0:
        return f"{future} today"
    n = abs(days)
    unit = "day" if n == 1 else "days"
    return f"{n} {unit} {past}" if days < 0 else f"{future} in {n} {unit}"


def compute(v: CaseView, today: date) -> dict[str, Any]:
    if v.state in _EXCLUDED or v.red_flag_open:
        return {"level": "none", "points": 0, "reasons": [], "excluded": True}
    reasons: list[dict[str, Any]] = []
    if v.failed_contact_attempts >= 2 and v.reached_contacts == 0:
        reasons.append(_reason("RISK-FAILED", f"{v.failed_contact_attempts} failed attempts"))
    if v.no_show_count > 0 or v.state == S.NO_SHOW:
        reasons.append(_reason("RISK-NOSHOW", f"{max(v.no_show_count, 1)} missed"))
    if v.reschedule_count >= 2:
        reasons.append(_reason("RISK-RESCHED", f"{v.reschedule_count} times"))
    left = BARRIER_MAX
    for b in v.barriers_open:
        if left <= 0:
            break
        pts = min(2, left)
        left -= pts
        reasons.append(_reason("RISK-BARRIER", b, points=pts, help=BARRIER_HELP.get(b)))
    if not v.phone_valid:
        reasons.append(_reason("RISK-NO-PHONE"))
    if "reminder" in v.ladder_steps and "reminder" not in v.ladder_held and v.reached_contacts == 0:
        reasons.append(_reason("RISK-SILENT"))
    if v.due_date and v.state in _NOT_BOOKED and (v.due_date - today).days <= 7:
        days = (v.due_date - today).days
        reasons.append(_reason("RISK-DEADLINE", _days(days, "overdue", "due")))
    appt = (v.appointment or {}).get("date") if v.state == S.ACTION_SCHEDULED else None
    if appt:
        try:
            d = (date.fromisoformat(str(appt)[:10]) - today).days
        except ValueError:
            d = None
        if d is not None and 0 <= d <= 3 and (v.barriers_open or v.reached_contacts == 0):
            reasons.append(_reason("RISK-APPT-SOON", "today" if d == 0 else f"in {d} day{'s' if d != 1 else ''}"))
    points = sum(r["points"] for r in reasons)
    level = "high" if points >= HIGH_AT else "watch" if points >= WATCH_AT else "none"
    return {"level": level, "points": points, "reasons": reasons, "excluded": False}


def rules_table() -> dict[str, Any]:
    return {
        "levels": {"watch": WATCH_AT, "high": HIGH_AT},
        "rules": [{"id": r.id, "points": r.points, "label": r.label, "help": r.help} for r in RULES],
        "barrier_help": BARRIER_HELP,
        "note": "Rules chosen by the team, not a validated prediction. No percentages. Never changes the case or "
        "the priority tier; never contacts anyone.",
    }
