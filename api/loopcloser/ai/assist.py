"""Gemini helpers. Gemini only DRAFTS text for staff: a case summary and a "Prepare for the call" guide.

It never decides urgency, priority, pathway, closure, or anything clinical, and it never changes a case.
This module returns text drafts only. It has no access to the repository or to domain commands, and a test
(tests/test_ai_boundary.py) enforces that it never imports them. Inputs are masked case facts, never names
or phone numbers. Every call-prep draft is checked by ai/verify.py before anyone sees it.

Backends (GEMINI_BACKEND): "vertex" (Vertex AI with the service account's Application Default Credentials,
used in production), "api_key" (Google AI Studio key, local experiments only), "off" (deterministic mock).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from loopcloser.ai.verify import Verification, verify_draft

log = logging.getLogger("loopcloser.ai")

AI_LABEL = "AI draft. Not medical advice. A staff member must review it."
PROMPT_VERSION = "call-prep@2"
SYSTEM_RULES = (
    "You help care-navigation staff. You only summarize or rephrase the facts given. "
    "Never give a diagnosis, treatment advice, urgency, priority, or a recommendation about clinical care. "
    "If asked to, say that a clinician must decide. Use plain language."
)
CALL_PREP_RULES = (
    SYSTEM_RULES + " You write a short guide that a health worker reads before phoning a patient about a "
    "screening follow-up. Use only the facts given. Every number and date you write must appear exactly in the "
    "facts; if a fact is missing, say it is not recorded. Do not invent phone numbers, names, clinics, times or "
    "counts. Names and phone numbers are withheld on purpose; do not mention them or say they are missing. "
    "Do not number the sections; use these four headings, each followed by one to three '-' bullets: "
    "Before you call, What to explain, Barriers to ask about, What to record after the call. "
    "Under 'What to explain', restate the next action exactly as given and say a clinician decides anything "
    "clinical. Never tell the patient their result is serious or not serious. Keep it under 160 words."
)
SAFE_FIELDS = (
    "id",
    "state",
    "screening_type",
    "pathway_id",
    "pathway_version",
    "next_action",
    "due_date",
    "contact_attempts",
    "failed_contact_attempts",
    "escalation_level",
    "owner",
)


@dataclass(frozen=True)
class AIBackend:
    kind: str = "off"  # "vertex" | "api_key" | "off"
    model: str = "gemini-3.8-flash"
    project: str | None = None
    location: str = "global"
    api_key: str | None = None

    @property
    def live(self) -> bool:
        return (self.kind == "vertex" and bool(self.project)) or (self.kind == "api_key" and bool(self.api_key))


@dataclass(frozen=True)
class AIDraft:
    text: str
    label: str = AI_LABEL
    model: str | None = None
    mock: bool = True
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int | None = None
    verification: Verification | None = None


def _masked(case: dict) -> dict:
    return {k: case.get(k) for k in SAFE_FIELDS if k in case}


_clients: dict[tuple, Any] = {}


def _client(b: AIBackend):
    key = (b.kind, b.project, b.location, b.api_key)
    if key not in _clients:
        from google import genai
        from google.genai import types

        opts = types.HttpOptions(timeout=30_000)
        if b.kind == "vertex":
            _clients[key] = genai.Client(vertexai=True, project=b.project, location=b.location, http_options=opts)
        else:
            _clients[key] = genai.Client(api_key=b.api_key, http_options=opts)
    return _clients[key]


def _generate(prompt: str, backend: AIBackend, system: str = SYSTEM_RULES, max_tokens: int = 1024) -> AIDraft | None:
    if not backend.live:
        return None
    from google.genai import types

    t = time.perf_counter()
    resp = _client(backend).models.generate_content(
        model=backend.model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    um = resp.usage_metadata
    usage = {
        "input_tokens": int(getattr(um, "prompt_token_count", 0) or 0),
        "output_tokens": int(getattr(um, "candidates_token_count", 0) or 0),
        "thinking_tokens": int(getattr(um, "thoughts_token_count", 0) or 0),
    }
    return AIDraft(
        text=(resp.text or "").strip(),
        model=getattr(resp, "model_version", None) or backend.model,
        mock=False,
        usage=usage,
        latency_ms=int((time.perf_counter() - t) * 1000),
    )


def summarize_case(case: dict, *, backend: AIBackend | None = None) -> AIDraft:
    facts = _masked(case)
    prompt = f"Summarize this follow-up case for staff in 2 sentences. Facts: {facts}"
    draft = _generate(prompt, backend or AIBackend())
    if draft:
        return draft
    return AIDraft(
        text=(
            f"Case {facts.get('id')} is at '{facts.get('state')}'. Next action: "
            f"{facts.get('next_action')} (due {facts.get('due_date')})."
        )
    )


def _mock_call_prep(f: dict[str, Any]) -> str:
    barriers = ", ".join(f.get("open_barriers") or []) or "none recorded"
    return "\n".join(
        [
            "Before you call",
            f"- Case {f.get('case_id')}, status: {f.get('status')}. Previous attempts: {f.get('contact_attempts')}, "
            f"failed: {f.get('failed_contact_attempts')}.",
            "What to explain",
            f"- Next step: {f.get('next_action')}. Deadline: {f.get('due_date')}.",
            "- A clinician decides anything clinical.",
            "Barriers to ask about",
            f"- Open barriers: {barriers}.",
            "What to record after the call",
            "- The call result, any new barrier, and the booked date if the patient agrees.",
        ]
    )


def prepare_call(facts: dict[str, Any], *, backend: AIBackend | None = None) -> AIDraft:
    """Draft a call guide from masked facts, then verify it against those same facts."""
    b = backend or AIBackend()
    prompt = "Case facts (JSON):\n" + json.dumps(facts, ensure_ascii=False, sort_keys=True)
    draft = None
    try:
        draft = _generate(prompt, b, system=CALL_PREP_RULES)
    except Exception:  # noqa: BLE001 - a failed draft must never break the case page
        log.exception("call-prep draft failed")
    if draft is None or not draft.text:
        draft = AIDraft(text=_mock_call_prep(facts), model=None, mock=True)
    v = verify_draft(draft.text, facts)
    return AIDraft(
        text=draft.text,
        model=draft.model,
        mock=draft.mock,
        usage=draft.usage,
        latency_ms=draft.latency_ms,
        verification=v,
    )
