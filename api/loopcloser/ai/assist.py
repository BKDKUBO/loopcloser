"""Gemini helpers. Today Gemini only drafts a staff case SUMMARY (POST /api/ai/cases/{id}/summary).

Explanations and a translated help chat were planned but are not built.

It never decides urgency, priority, pathway, closure, or anything clinical.
This module returns text drafts only. It has no access to the repository or to
domain commands, and a test (tests/test_ai_boundary.py) enforces that it never
imports them. Inputs are masked case fields, never names or phone numbers.
"""

from __future__ import annotations

from dataclasses import dataclass

AI_LABEL = "AI draft. Not medical advice. A staff member must review it."
SYSTEM_RULES = (
    "You help care-navigation staff. You only summarize or rephrase the facts given. "
    "Never give a diagnosis, treatment advice, urgency, priority, or a recommendation about clinical care. "
    "If asked to, say that a clinician must decide. Use plain language."
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
class AIDraft:
    text: str
    label: str = AI_LABEL
    model: str | None = None
    mock: bool = True


def _masked(case: dict) -> dict:
    return {k: case.get(k) for k in SAFE_FIELDS if k in case}


def _generate(prompt: str, api_key: str | None, model: str) -> AIDraft | None:
    if not api_key:
        return None
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000))
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_RULES, temperature=0.2),
    )
    return AIDraft(text=(resp.text or "").strip(), model=model, mock=False)


def summarize_case(case: dict, *, api_key: str | None = None, model: str = "gemini-3.8-flash") -> AIDraft:
    facts = _masked(case)
    prompt = f"Summarize this follow-up case for staff in 2 sentences. Facts: {facts}"
    draft = _generate(prompt, api_key, model)
    if draft:
        return draft
    return AIDraft(
        text=(
            f"Case {facts.get('id')} is at '{facts.get('state')}'. Next action: "
            f"{facts.get('next_action')} (due {facts.get('due_date')})."
        )
    )
