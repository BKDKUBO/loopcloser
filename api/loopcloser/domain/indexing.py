"""Stored query fields for the Today view and the escalation ladder.

Priority and lanes depend on the date, so they are computed at read time for display. To avoid reading
every case on every page load, each case document also stores a few `idx_*` fields computed when the
case is written:

  idx_lane        Today lane (needs_action, overdue, waiting, completed)
  idx_tier        priority tier, idx_rank its sort rank (closed cases sort last), idx_score points
  idx_due         due date (ISO), far future when missing, for a stable sort
  idx_people      owner and backup owner, so a worker query is one array-contains filter
  idx_recheck     next date on which the tier or lane can change only because time passed
  idx_ladder_due  next date an escalation ladder step becomes due, far future when none can be
  idx_status      plain status (to_contact, booked, needs_review, done), for the Today summary
  idx_lost        true when the patient cannot be reached (next_action.lost_contact)

`idx_recheck` and `idx_ladder_due` let the daily (or "advance the clock") job query only the cases that
actually need work instead of scanning them all. These fields are a rebuildable cache, like the
projection itself; the event log stays the source of truth.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import ladder as ladder_mod
from . import priority as prio
from .case import CaseView
from .localtime import local_date
from .next_action import lost_contact, plain_status
from .states import CaseState as S

LANES = ("needs_action", "overdue", "waiting", "completed")
TIERS = ("urgent", "high", "moderate", "routine")
TIER_RANK = {"urgent": 0, "high": 1, "moderate": 2, "routine": 3}
FAR = "9999-12-31"
_WAITING = frozenset({S.PATIENT_NOTIFIED, S.ACTION_SCHEDULED, S.RESCHEDULED})
_DONE = frozenset({S.CLOSED, S.VISIT_COMPLETED})


def lane_for(v: CaseView, today: date) -> str:
    """Same rule as the web's former client-side grouping (web/lib/lanes.ts)."""
    if v.state in _DONE:
        return "completed"
    if v.due_date and v.due_date < today:
        return "overdue"
    if v.state in _WAITING and not v.red_flag_open:
        return "waiting"
    return "needs_action"


def recheck_on(v: CaseView, today: date) -> date | None:
    """Next date when only the passing of time changes the tier or lane (due soon at due-3, overdue at due+1)."""
    if not v.due_date or v.state in _DONE:
        return None
    for d in (v.due_date - timedelta(days=3), v.due_date + timedelta(days=1)):
        if d > today:
            return d
    return None


def ladder_due(v: CaseView, steps: tuple[ladder_mod.Step, ...] = ladder_mod.DEFAULT_LADDER) -> date | None:
    """Earliest date a not-yet-run, currently needed ladder step becomes due. Any write recomputes it."""
    if v.state == S.CLOSED or v.automation_paused or not v.opened_at:
        return None
    opened = local_date(v.opened_at)
    days = [s.day for s in steps if s.id != "upload" and s.id not in v.ladder_steps and ladder_mod.needed(s.id, v)]
    return opened + timedelta(days=min(days)) if days else None


def index_fields(
    v: CaseView, today: date, steps: tuple[ladder_mod.Step, ...] = ladder_mod.DEFAULT_LADDER
) -> dict[str, Any]:
    p = prio.compute(v, today)
    closed = v.state == S.CLOSED
    rc = recheck_on(v, today)
    ld = ladder_due(v, steps)
    return {
        "idx_lane": lane_for(v, today),
        "idx_tier": p.tier,
        "idx_rank": TIER_RANK[p.tier] + (10 if closed else 0),
        "idx_score": p.score,
        "idx_due": v.due_date.isoformat() if v.due_date else FAR,
        "idx_people": sorted({x for x in (v.owner, v.backup_owner) if x}),
        "idx_recheck": rc.isoformat() if rc else FAR,
        "idx_ladder_due": ld.isoformat() if ld else FAR,
        "idx_as_of": today.isoformat(),
        "idx_status": plain_status(v),
        "idx_lost": lost_contact(v),
        # Simulated slot capacity (domain/scheduling.py): which slot an open, booked case holds.
        **_slot_fields(v),
    }


def _slot_fields(v: CaseView) -> dict[str, str]:
    sid = (v.appointment or {}).get("slot_id") if v.state == S.ACTION_SCHEDULED else None
    return {"idx_slot": sid or "", "idx_slot_clinic": sid.split("|", 1)[0] if sid else ""}


def sort_key(doc: dict[str, Any]) -> tuple:
    """The order every lane query uses (Firestore composite index in firestore.indexes.json)."""
    return (doc["idx_rank"], -doc["idx_score"], doc["idx_due"], doc["id"])
