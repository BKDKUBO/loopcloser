"""Append-only event log. Every action is an immutable, timestamped event.

Case state, timelines and metrics are derived from events (PLAN_FINAL.md section 15).
Events are never updated or deleted. The stores expose no update or delete method.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .roles import Role

ActorKind = Literal["human", "system", "automation"]


class Actor(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    role: Role
    kind: ActorKind = "human"

    @property
    def is_human(self) -> bool:
        return self.kind == "human" and self.role != Role.SYSTEM


SYSTEM_ACTOR = Actor(id="system", role=Role.SYSTEM, kind="system")
AUTOMATION_ACTOR = Actor(id="automation", role=Role.SYSTEM, kind="automation")


class EventType(StrEnum):
    CASE_OPENED = "case_opened"
    OWNER_ASSIGNED = "owner_assigned"
    STATE_CHANGED = "state_changed"
    CONTACT_ATTEMPT = "contact_attempt"
    NOTIFICATION_STATUS = "notification_status"
    RED_FLAG_REPORTED = "red_flag_reported"
    AUTOMATION_RESUMED = "automation_resumed"
    NOTE_ADDED = "note_added"
    CASE_CLOSED = "case_closed"
    BARRIER_REPORTED = "barrier_reported"
    BARRIER_RESOLVED = "barrier_resolved"
    PRIORITY_OVERRIDDEN = "priority_overridden"
    LADDER_STEP = "ladder_step"
    # AI drafts for staff. Audit only: they never change case state (see case.py).
    AI_DRAFT_CREATED = "ai_draft_created"
    AI_DRAFT_DECISION = "ai_draft_decision"
    # Staff looked at the (SIMULATED) name and phone. Audit only: never changes the case.
    CONTACT_REVEALED = "contact_revealed"
    # Staff recorded the patient's consent to be contacted (rule GATE-1). Changes the consent gate only.
    CONSENT_RECORDED = "consent_recorded"
    # Staff downloaded the case summary or audit trail (rule PRIV-2). Audit only: never changes the case.
    CASE_EXPORTED = "case_exported"
    # The patient replied to an SMS with a keyword (YES / RESCHED / STOP). Simulated in this build (rule MSG-4).
    SMS_REPLY_RECEIVED = "sms_reply_received"


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    case_id: str
    seq: int = Field(ge=1)
    type: EventType
    at: datetime
    actor: Actor
    rule_id: str | None = None
    fields_used: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def make_id(case_id: str, seq: int) -> str:
        return f"{case_id}-{seq:06d}"

    def to_doc(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> Event:
        return cls.model_validate(doc)
