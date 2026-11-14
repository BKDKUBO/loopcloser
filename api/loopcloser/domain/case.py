"""Case projection: fold the event log into the current view of a case.

The projection is a cache. It can always be rebuilt from events, and tests check
that a stored projection equals a fresh rebuild.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from .events import Event, EventType
from .states import CaseState


class CaseView(BaseModel):
    id: str
    participant_id: str
    screening_id: str
    screening_type: str
    severity: str
    pathway_id: str
    pathway_version: str
    pathway_signoff_status: str
    state: CaseState = CaseState.NEW_RESULT
    previous_state: CaseState | None = None
    clinical_urgency: str = "standard"  # "urgent" | "standard". From the upload and red flags, never from AI.
    # Ownership (PLAN_FINAL.md section 4)
    owner: str | None = None
    backup_owner: str | None = None
    clinician_reviewer: str | None = None
    next_action: str | None = None
    due_date: date | None = None
    escalation_level: int = 0
    contact_attempts: int = 0
    failed_contact_attempts: int = 0
    last_contact_attempt: datetime | None = None
    closure_reason: str | None = None
    closure_evidence: str | None = None
    closure_evidence_detail: dict[str, Any] | None = None  # structured: visit_date, facility, record_number
    signed_off_by: str | None = None
    # Participant context used by priority rules (from the upload, never from AI)
    language: str = "en"
    comorbidity: bool = False
    location: str | None = None
    age_band: str | None = None
    phone_valid: bool = True
    barriers_open: list[str] = Field(default_factory=list)
    no_show_count: int = 0
    reached_contacts: int = 0
    appointment: dict[str, Any] | None = None
    priority_override: dict[str, Any] | None = None
    ladder_steps: list[str] = Field(default_factory=list)
    # Safety
    automation_paused: bool = False
    red_flag_open: bool = False
    # Bookkeeping
    patient_uid: str | None = None  # Firebase uid of the patient, when linked. Used by Firestore rules.
    synthetic: bool = False
    data_label: str | None = None  # "SIMULATED" for generated data
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0  # seq of the last applied event
    data_quality: list[str] = Field(default_factory=list)

    def to_doc(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _apply(view: CaseView | None, ev: Event) -> CaseView:
    p = ev.payload
    if ev.type == EventType.CASE_OPENED:
        if view is not None:
            raise ValueError("case_opened must be the first event")
        return CaseView(
            id=ev.case_id,
            participant_id=p["participant_id"],
            screening_id=p["screening_id"],
            screening_type=p["screening_type"],
            severity=p["severity"],
            pathway_id=p["pathway_id"],
            pathway_version=p["pathway_version"],
            pathway_signoff_status=p["pathway_signoff_status"],
            clinical_urgency=p.get("clinical_urgency", "standard"),
            next_action=p.get("next_action"),
            due_date=p.get("due_date"),
            owner=p.get("owner"),
            patient_uid=p.get("patient_uid"),
            language=p.get("language") or "en",
            comorbidity=bool(p.get("comorbidity", False)),
            location=p.get("location"),
            age_band=p.get("age_band"),
            phone_valid=bool(p.get("phone_valid", True)),
            synthetic=bool(p.get("synthetic", False)),
            data_label=p.get("data_label"),
            opened_at=ev.at,
            updated_at=ev.at,
            version=ev.seq,
        )
    if view is None:
        raise ValueError("first event must be case_opened")

    v = view.model_copy(deep=True)
    if ev.type == EventType.OWNER_ASSIGNED:
        for f in ("owner", "backup_owner", "clinician_reviewer"):
            if f in p:
                setattr(v, f, p[f])
    elif ev.type == EventType.STATE_CHANGED:
        v.previous_state = CaseState(p["from"])
        v.state = CaseState(p["to"])
        if v.state == CaseState.ESCALATED:
            v.escalation_level += 1
        if v.state == CaseState.NO_SHOW:
            v.no_show_count += 1
        if "appointment" in p:
            v.appointment = p["appointment"]
        if "next_action" in p:
            v.next_action = p["next_action"]
        if "due_date" in p:
            v.due_date = p["due_date"]
        if v.state == CaseState.RESOLVED_BY_HUMAN:
            v.red_flag_open = False
    elif ev.type == EventType.CONTACT_ATTEMPT:
        v.contact_attempts += 1
        if p.get("result") == "reached":
            v.reached_contacts += 1
        else:
            v.failed_contact_attempts += 1
        v.last_contact_attempt = ev.at
    elif ev.type == EventType.RED_FLAG_REPORTED:
        v.red_flag_open = True
        v.automation_paused = True
        v.clinical_urgency = "urgent"
        if p.get("state_change", True):
            v.previous_state = v.state
            v.state = CaseState.RED_FLAG_REPORTED
    elif ev.type == EventType.AUTOMATION_RESUMED:
        v.automation_paused = False
    elif ev.type == EventType.CASE_CLOSED:
        v.previous_state = v.state
        v.state = CaseState.CLOSED
        v.closure_reason = p["closure_reason"]
        v.closure_evidence = p.get("evidence_ref")
        v.closure_evidence_detail = p.get("evidence")
        v.signed_off_by = p.get("signed_off_by")
    elif ev.type == EventType.BARRIER_REPORTED:
        if p["barrier"] not in v.barriers_open:
            v.barriers_open.append(p["barrier"])
    elif ev.type == EventType.BARRIER_RESOLVED:
        v.barriers_open = [b for b in v.barriers_open if b != p["barrier"]]
    elif ev.type == EventType.PRIORITY_OVERRIDDEN:
        v.priority_override = (
            {
                "tier": p["tier"],
                "reason": p["reason"],
                "note": p["note"],
                "by": ev.actor.id,
                "at": ev.at.isoformat(),
            }
            if p.get("tier")
            else None
        )
    elif ev.type == EventType.LADDER_STEP:
        if p["step"] not in v.ladder_steps:
            v.ladder_steps.append(p["step"])
    # NOTIFICATION_STATUS, NOTE_ADDED, CONTACT_REVEALED and the AI_DRAFT_* audit events never change state.
    v.updated_at = ev.at
    v.version = ev.seq
    return v


def _data_quality(v: CaseView) -> list[str]:
    issues = []
    if v.state != CaseState.CLOSED and not v.owner:
        issues.append("no_owner")
    if v.clinical_urgency == "urgent" and not v.owner:
        issues.append("urgent_without_owner")
    return issues


def project(events: list[Event]) -> CaseView:
    if not events:
        raise ValueError("no events")
    view: CaseView | None = None
    expected = 1
    for ev in sorted(events, key=lambda e: e.seq):
        if ev.seq != expected:
            raise ValueError(f"event log gap: expected seq {expected}, got {ev.seq}")
        view = _apply(view, ev)
        expected += 1
    assert view is not None
    view.data_quality = _data_quality(view)
    return view
