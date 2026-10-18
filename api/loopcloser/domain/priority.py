"""Follow-up priority: deterministic points rules (PLAN_FINAL.md section 7).

Shown as "Follow-up priority" with a "Why this priority?" list of the rules that
fired. Clinical urgency is a separate badge. No ML, no probabilities, no AI.
Barriers are logistics, never presented as a medical issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .case import CaseView
from .states import CaseState as S

SUPPORTED_LANGUAGES = frozenset({"en", "fil"})
LOGISTIC_BARRIERS = ("transport", "cost", "work")
TIERS = ("routine", "moderate", "high", "urgent")
TIER_LABELS = {"urgent": "Urgent", "high": "High", "moderate": "Moderate", "routine": "Routine"}
TIER_GUIDANCE = {
    "urgent": "Immediate human review",
    "high": "Active navigation within 24 to 48 hours",
    "moderate": "Booking help and reminders",
    "routine": "Scheduled follow-up and education",
}
_BOOKED = frozenset({S.ACTION_SCHEDULED, S.VISIT_COMPLETED, S.CLOSED})
# States that imply someone already talked with the patient.
_CONTACTED = frozenset({S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED, S.CLOSED, S.RESCHEDULED})
_DONE = frozenset({S.VISIT_COMPLETED, S.CLOSED})

# rule id, points, label
RULES: tuple[tuple[str, int, str], ...] = (
    ("PRI-CRITICAL", 5, "Critical result"),
    ("PRI-RED-FLAG", 5, "Red flag reported"),
    ("PRI-OVERDUE", 4, "Deadline passed"),
    ("PRI-DUE-SOON", 3, "Deadline within 3 days"),
    ("PRI-NO-APPT", 3, "No appointment"),
    ("PRI-MISSED", 2, "Previous missed appointment"),
    ("PRI-BARRIER", 2, "Transport, cost or work barrier"),
    ("PRI-NO-CONTACT", 2, "No successful contact"),
    ("PRI-COMORBID", 1, "Comorbidity"),
    ("PRI-LANGUAGE", 1, "Unsupported language"),
)
POINTS = {r[0]: r[1] for r in RULES}
LABELS = {r[0]: r[2] for r in RULES}


def tier_for(score: int) -> str:
    if score >= 8:
        return "urgent"
    if score >= 5:
        return "high"
    if score >= 3:
        return "moderate"
    return "routine"


@dataclass
class Priority:
    score: int
    computed_tier: str
    tier: str
    reasons: list[dict[str, Any]] = field(default_factory=list)
    override: dict[str, Any] | None = None

    @property
    def explanation(self) -> str:
        why = "; ".join(f"{r['label'].lower()} (+{r['points']})" for r in self.reasons) or "no rules fired"
        text = f"{TIER_LABELS[self.computed_tier]} ({self.score}): {why}."
        if self.override:
            text += f" Overridden to {TIER_LABELS[self.tier]} by {self.override['by']}: {self.override['reason']}."
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "tier": self.tier,
            "tier_label": TIER_LABELS[self.tier],
            "computed_tier": self.computed_tier,
            "guidance": TIER_GUIDANCE[self.tier],
            "reasons": self.reasons,
            "override": self.override,
            "explanation": self.explanation,
        }


def compute(v: CaseView, today: date) -> Priority:
    if v.state == S.CLOSED:
        return Priority(score=0, computed_tier="routine", tier="routine")
    fired: list[tuple[str, str | None]] = []
    if v.severity == "critical":
        fired.append(("PRI-CRITICAL", None))
    if v.red_flag_open:
        fired.append(("PRI-RED-FLAG", None))
    if v.due_date and v.state not in _DONE:
        days = (v.due_date - today).days
        if days < 0:
            fired.append(("PRI-OVERDUE", f"{-days} days past {v.due_date.isoformat()}"))
        elif days <= 3:
            fired.append(("PRI-DUE-SOON", f"due {v.due_date.isoformat()}"))
    if v.state not in _BOOKED:
        fired.append(("PRI-NO-APPT", None))
    if v.no_show_count:
        fired.append(("PRI-MISSED", f"{v.no_show_count} missed"))
    barriers = [b for b in v.barriers_open if b in LOGISTIC_BARRIERS]
    if barriers:
        fired.append(("PRI-BARRIER", ", ".join(barriers)))
    if v.reached_contacts == 0 and v.state not in _CONTACTED:
        fired.append(("PRI-NO-CONTACT", None))
    if v.comorbidity:
        fired.append(("PRI-COMORBID", None))
    if v.language not in SUPPORTED_LANGUAGES:
        fired.append(("PRI-LANGUAGE", v.language))
    reasons = [{"rule_id": rid, "points": POINTS[rid], "label": LABELS[rid], "detail": d} for rid, d in fired]
    score = sum(r["points"] for r in reasons)
    computed = tier_for(score)
    tier = v.priority_override["tier"] if v.priority_override else computed
    return Priority(score=score, computed_tier=computed, tier=tier, reasons=reasons, override=v.priority_override)
