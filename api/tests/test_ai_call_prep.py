"""'Prepare for the call' AI draft: verification, Use/Discard, and the rule that AI never changes a case."""

import pytest
from fastapi.testclient import TestClient

from loopcloser.ai import assist
from loopcloser.ai.assist import AIBackend, AIDraft, prepare_call
from loopcloser.ai.verify import verify_draft
from loopcloser.main import create_app
from loopcloser.store.memory import MemoryRepository

FACTS = {
    "case_id": "C-7",
    "today": "2026-11-09",
    "due_date": "2026-11-12",
    "days_until_due": 3,
    "contact_attempts": 2,
    "failed_contact_attempts": 2,
    "open_barriers": ["transport"],
    "follow_up_priority": "urgent (9 points)",
}


# ---------------------------------------------------------------- verification (pure)


@pytest.mark.parametrize(
    "text",
    [
        "Deadline: 2026-11-12. Two failed attempts so far.",
        "Call before Nov 12; it is due in 3 days.",
        "Due 12 November 2026 (in three days). Priority urgent (9 points).",
        "Before you call\n1. Check case C-7.\n2. There were 2 attempts.",
        "Nobyembre 12 ang deadline.",
    ],
)
def test_supported_numbers_and_dates_pass(text):
    v = verify_draft(text, FACTS)
    assert v.verified, v.unsupported
    assert v.checked


@pytest.mark.parametrize(
    "text,bad",
    [
        ("Deadline: 2026-11-15.", "2026-11-15"),
        ("Call before Nov 14.", "Nov 14"),
        ("Call the clinic on 0917 555 1234.", "0917"),
        ("There were 4 failed attempts.", "4"),
        ("Due in five days.", "five"),
        ("Book by 11/20.", "11/20"),
        ("Her blood pressure was 150/95.", "150"),
    ],
)
def test_invented_numbers_and_dates_are_flagged(text, bad):
    v = verify_draft(text, FACTS)
    assert not v.verified
    assert bad in v.unsupported


def test_number_words_in_the_facts_are_allowed():
    facts = {**FACTS, "next_action": "Repeat on two different days; 140 and/or 90 mmHg."}
    assert verify_draft("Repeat on two different days (140 and/or 90 mmHg).", facts).verified
    assert not verify_draft("Repeat on 6 different days.", FACTS).verified


def test_text_without_numbers_is_verified():
    assert verify_draft("Ask about transport. A clinician decides anything clinical.", FACTS).verified


# ---------------------------------------------------------------- prepare_call with a mocked model


def _fake(text):
    def gen(prompt, backend, system=None, max_tokens=1024):
        assert "Case facts" in prompt and "0917" not in prompt
        return AIDraft(text=text, model="gemini-test", mock=False, usage={"input_tokens": 10, "output_tokens": 5})

    return gen


def test_prepare_call_verifies_model_output(monkeypatch):
    monkeypatch.setattr(assist, "_generate", _fake("Due 2026-11-12, in 3 days."))
    d = prepare_call(FACTS, backend=AIBackend(kind="vertex", project="p"))
    assert not d.mock and d.verification.verified and d.model == "gemini-test"


def test_prepare_call_flags_hallucinated_date(monkeypatch):
    monkeypatch.setattr(assist, "_generate", _fake("Due 2026-12-01."))
    d = prepare_call(FACTS, backend=AIBackend(kind="vertex", project="p"))
    assert not d.verification.verified and d.verification.unsupported == ["2026-12-01"]


def test_prepare_call_falls_back_to_mock_when_model_fails(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(assist, "_generate", boom)
    d = prepare_call(FACTS, backend=AIBackend(kind="vertex", project="p"))
    assert d.mock and d.verification.verified


def test_mock_draft_always_verifies():
    d = prepare_call(FACTS)  # backend off
    assert d.mock and d.verification.verified, d.verification.unsupported


# ---------------------------------------------------------------- API: Use / Discard, audit, no state change

H = {
    "worker": {"x-demo-role": "worker", "x-demo-user": "demo-worker-01"},
    "coordinator": {"x-demo-role": "coordinator", "x-demo-user": "demo-coord-01"},
    "patient": {"x-demo-role": "patient", "x-demo-user": "demo-patient-01"},
    "program_manager": {"x-demo-role": "program_manager", "x-demo-user": "demo-pm-01"},
}
CASE = {
    "case_id": "C-1",
    "participant_id": "P-000042",
    "screening_id": "S-1",
    "screening_type": "fit",
    "result": "positive",
    "severity": "abnormal",
    "screened_at": "2026-10-10",
    "owner": "demo-worker-01",
    "barriers": ["transport"],
}


@pytest.fixture
def client(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="5000", RATE_LIMIT_SENSITIVE_PER_MINUTE="500"
    )
    c = TestClient(create_app(cfg, MemoryRepository()))
    assert c.post("/api/cases", json=CASE, headers=H["coordinator"]).status_code == 201
    return c


def _state(c):
    d = c.get("/api/cases/C-1", headers=H["worker"]).json()
    return {k: d[k] for k in ("state", "owner", "due_date", "next_action", "priority", "red_flag_open")}


def test_draft_is_logged_and_changes_nothing(client):
    before = _state(client)
    r = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"])
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["verified"] and d["text"] and d["label"].startswith("AI draft") and d["decision"] is None
    assert _state(client) == before
    types = [e["type"] for e in client.get("/api/cases/C-1/events", headers=H["worker"]).json()]
    assert types[-1] == "ai_draft_created"


def test_use_then_second_decision_refused(client):
    seq = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"]).json()["draft_seq"]
    before = _state(client)
    r = client.post(f"/api/ai/cases/C-1/call-prep/{seq}/decision", json={"decision": "use"}, headers=H["worker"])
    assert r.status_code == 200 and r.json()["draft"]["decision"] == "use"
    assert _state(client) == before
    r = client.post(f"/api/ai/cases/C-1/call-prep/{seq}/decision", json={"decision": "discard"}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "AI-3"
    ev = client.get("/api/cases/C-1/events", headers=H["worker"]).json()[-1]
    assert ev["type"] == "ai_draft_decision" and ev["payload"] == {"draft_seq": seq, "decision": "use"}


def test_discard(client):
    seq = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"]).json()["draft_seq"]
    r = client.post(f"/api/ai/cases/C-1/call-prep/{seq}/decision", json={"decision": "discard"}, headers=H["worker"])
    assert r.json()["draft"]["decision"] == "discard"
    assert client.get("/api/ai/cases/C-1/call-prep", headers=H["worker"]).json()["draft"]["decision"] == "discard"


def test_unverified_draft_is_withheld_and_cannot_be_used(client, monkeypatch):
    monkeypatch.setattr(assist, "_generate", _fake("Call 0917 555 1234 before 2027-01-01."))
    import loopcloser.main as main_mod

    monkeypatch.setattr(
        main_mod,
        "prepare_call",
        lambda facts, backend=None: assist.prepare_call(facts, backend=AIBackend("vertex", project="p")),
    )
    r = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"]).json()
    d = r["draft"]
    assert not d["verified"] and d["text"] is None and "2027-01-01" in d["unsupported"]
    r = client.post(
        f"/api/ai/cases/C-1/call-prep/{r['draft_seq']}/decision", json={"decision": "use"}, headers=H["worker"]
    )
    assert r.status_code == 422 and r.json()["rule_id"] == "AI-3"
    r = client.post(
        f"/api/ai/cases/C-1/call-prep/{d['draft_seq']}/decision", json={"decision": "discard"}, headers=H["worker"]
    )
    assert r.status_code == 200


def test_no_draft_while_red_flag_open(client):
    assert client.post("/api/cases/C-1/red-flag", json={}, headers=H["worker"]).status_code == 200
    r = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "AI-2"


def test_patient_and_program_manager_cannot_request_drafts(client):
    assert client.post("/api/ai/cases/C-1/call-prep", headers=H["patient"]).status_code == 403
    assert client.post("/api/ai/cases/C-1/call-prep", headers=H["program_manager"]).status_code == 403


def test_bad_decision_and_unknown_draft(client):
    seq = client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"]).json()["draft_seq"]
    r = client.post(f"/api/ai/cases/C-1/call-prep/{seq}/decision", json={"decision": "send"}, headers=H["worker"])
    assert r.status_code == 422
    r = client.post("/api/ai/cases/C-1/call-prep/1/decision", json={"decision": "use"}, headers=H["worker"])
    assert r.status_code == 404  # seq 1 is case_opened, not a draft


def test_facts_sent_to_model_are_masked(client, monkeypatch):
    seen = {}

    def spy(facts, backend=None):
        seen.update(facts)
        return prepare_call(facts)

    import loopcloser.main as main_mod

    monkeypatch.setattr(main_mod, "prepare_call", spy)
    client.post("/api/ai/cases/C-1/call-prep", headers=H["worker"])
    assert "participant_id" not in seen and "owner" not in seen and "patient_uid" not in seen
    assert seen["open_barriers"] == ["transport"] and seen["approved_template_to_use"] == "reminder"
    assert seen["status"] == "new result" and ("days_overdue" in seen or "days_until_due" in seen)
