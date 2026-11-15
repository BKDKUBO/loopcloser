"""Pass/hold gates (rule GATE-1). Deterministic checks shown on every case, so nobody acts on incomplete data.

Each gate is Pass or Hold, with what is missing. Patient-contact actions are blocked by the API while the
consent or contact-details gate is on Hold (main.py _check_contact_gates); the other gates warn. A person
still reviews every case before any patient contact: gates never contact anyone themselves.
"""

from __future__ import annotations

from typing import Any

from .case import CaseView
from .states import CaseState

RULE_ID = "GATE-1"
CONSENT_VALUES = frozenset({"yes", "no"})
# Channels that reach the patient's phone. A community health worker visit is not one of them.
PHONE_CHANNELS = frozenset({"call", "sms"})


def _gate(gid: str, label: str, ok: bool, detail: str, missing: str | None, blocks: tuple[str, ...]) -> dict[str, Any]:
    return {
        "id": gid,
        "label": label,
        "status": "pass" if ok else "hold",
        "detail": detail,
        "missing": None if ok else missing,
        "blocks": [] if ok else list(blocks),
        "rule_id": RULE_ID,
    }


def compute(v: CaseView) -> list[dict[str, Any]]:
    consent = v.contact_consent
    gates = [
        _gate(
            "consent",
            "Consent to contact",
            consent == "yes",
            "Consent to contact recorded"
            if consent == "yes"
            else "Patient declined to be contacted"
            if consent == "no"
            else "Consent to contact was not recorded",
            "The patient declined contact. A coordinator decides the next step."
            if consent == "no"
            else "Record consent to contact (in person or at screening) before calling or sending SMS.",
            ("call", "sms", "chw_visit") if consent == "no" else ("call", "sms"),
        ),
        _gate(
            "contact_details",
            "Contact details",
            v.phone_valid,
            "Valid mobile number on file" if v.phone_valid else "No valid mobile number on file",
            "Calls and SMS are on hold. Send a community health worker, or update the number.",
            ("call", "sms"),
        ),
        _gate(
            "result_on_file",
            "Result on file",
            bool(v.screening_id and v.severity and v.pathway_id),
            f"Screening record {v.screening_id} ({v.severity}) on pathway {v.pathway_id} v{v.pathway_version}",
            "No screening result on file. Do not contact the patient about a result we do not have.",
            ("call", "sms", "chw_visit"),
        ),
        _gate(
            "owner",
            "Owner assigned",
            bool(v.owner) or v.state == CaseState.CLOSED,
            f"Owner: {v.owner}" if v.owner else "Nobody owns this case",
            "Assign an owner, so one named person is accountable for the follow-up.",
            (),
        ),
        _gate(
            "red_flag",
            "No open red flag",
            not v.red_flag_open,
            "No open red flag" if not v.red_flag_open else "Red flag open: automation paused",
            "A person must resolve the red flag first (rule RF-1). Automation and AI drafts are paused.",
            (),
        ),
    ]
    return gates


def holds(v: CaseView) -> list[dict[str, Any]]:
    return [g for g in compute(v) if g["status"] == "hold"]


def blocking(v: CaseView, channel: str) -> list[dict[str, Any]]:
    """Gates on Hold that block this patient-contact channel ("call", "sms" or "chw_visit")."""
    return [g for g in holds(v) if channel in g["blocks"]]


def consent_ok(v: CaseView) -> bool:
    return v.contact_consent == "yes"
