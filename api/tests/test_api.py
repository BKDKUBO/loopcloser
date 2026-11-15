import pytest
from fastapi.testclient import TestClient

from loopcloser import auth
from loopcloser.config import ConfigError
from loopcloser.main import create_app, mask_participant
from loopcloser.store.memory import MemoryRepository

H = {
    r: {"x-demo-role": r, "x-demo-user": u}
    for r, u in [
        ("coordinator", "demo-coord-01"),
        ("worker", "demo-worker-01"),
        ("supervisor", "demo-sup-01"),
        ("program_manager", "demo-pm-01"),
        ("patient", "demo-patient-01"),
    ]
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
    "contact_consent": "yes",
}


@pytest.fixture
def client(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="5000", RATE_LIMIT_SENSITIVE_PER_MINUTE="500"
    )
    return TestClient(create_app(cfg, MemoryRepository()))


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200
    checks = r.json()["checks"]
    assert checks["pathways"] == 6 and checks["templates"] == 5 and checks["auth_mode"] == "firebase+demo"
    assert "x-request-id" in r.headers


def test_public_config(client):
    c = client.get("/api/public-config").json()
    assert c["demo_mode"] is True and "Firebase Auth" in c["auth"]


def test_requires_role(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"x-demo-role": "admin"}).status_code == 403
    me = client.get("/api/me", headers=H["worker"]).json()
    assert me["role"] == "worker" and me["demo"] is True and me["uid"] == "demo-worker-01"


def test_demo_users_always_get_demo_prefix(client):
    me = client.get("/api/me", headers={"x-demo-role": "supervisor", "x-demo-user": "real-admin"}).json()
    assert me["uid"] == "demo-real-admin"


def test_role_permissions(client):
    assert client.post("/api/cases", json=CASE, headers=H["worker"]).status_code == 403
    assert client.post("/api/cases", json=CASE, headers=H["program_manager"]).status_code == 403
    r = client.post("/api/cases", json=CASE, headers=H["coordinator"])
    assert r.status_code == 201
    body = r.json()
    assert body["participant_id"] == "P-••••42" and "patient_uid" not in body
    assert client.get("/api/cases", headers=H["worker"]).json()["total"] == 1
    assert client.get("/api/cases", headers={**H["worker"], "x-demo-user": "demo-worker-99"}).json()["total"] == 0
    assert client.get("/api/cases/C-1", headers=H["patient"]).status_code == 404
    assert client.get("/api/cases", headers=H["program_manager"]).json()["total"] == 1
    r = client.post("/api/cases/C-1/transition", json={"target": "reviewed"}, headers=H["program_manager"])
    assert r.status_code == 403


def test_case_has_priority_and_action(client):
    body = client.post("/api/cases", json=CASE | {"barriers": ["transport"]}, headers=H["coordinator"]).json()
    p = body["priority"]
    rules = {r["rule_id"] for r in p["reasons"]}
    assert {"PRI-NO-APPT", "PRI-BARRIER", "PRI-NO-CONTACT"} <= rules
    assert p["explanation"].startswith(p["tier_label"])
    assert body["recommended_action"]["kind"] == "barrier"
    detail = client.get("/api/cases/C-1", headers=H["coordinator"]).json()
    assert [s["id"] for s in detail["ladder"]][:3] == ["upload", "review", "contact"]


def test_guard_violation_returns_rule_id(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    r = client.post("/api/cases/C-1/transition", json={"target": "action_scheduled"}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "SM-1"
    r = client.post("/api/cases/C-1/close", json={"closure_reason": "x", "sign_off": True}, headers=H["worker"])
    assert r.status_code == 403


def test_override_supervisor_only_and_logged(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    body = {"tier": "urgent", "reason": "worsening_symptoms", "note": "called, patient worse"}
    assert client.post("/api/cases/C-1/priority-override", json=body, headers=H["coordinator"]).status_code == 403
    r = client.post("/api/cases/C-1/priority-override", json=body, headers=H["supervisor"]).json()
    assert r["priority"]["tier"] == "urgent" and r["priority"]["override"]["by"] == "demo-sup-01"
    assert "Overridden to Urgent" in r["priority"]["explanation"]
    ev = client.get("/api/cases/C-1/events", headers=H["supervisor"]).json()
    assert ev[-1]["type"] == "priority_overridden" and ev[-1]["rule_id"] == "PRI-1"
    bad = client.post("/api/cases/C-1/priority-override", json=body | {"note": " "}, headers=H["supervisor"])
    assert bad.status_code == 422


def test_messages_use_templates_only(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    r = client.post(
        "/api/cases/C-1/messages/preview", json={"template_id": "result-notice", "language": "fil"}, headers=H["worker"]
    ).json()
    assert r["status"] == "pending_review" and "colonoscopy" in r["text"] and "Hindi ito diagnosis" in r["text"]
    r = client.post(
        "/api/cases/C-1/messages", json={"template_id": "sms-minimal", "language": "en"}, headers=H["worker"]
    ).json()
    assert r["simulated"] and "call the clinic" in r["message"]["text"]
    assert (
        client.post(
            "/api/cases/C-1/messages", json={"template_id": "free-text", "language": "en"}, headers=H["worker"]
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/cases/C-1/messages", json={"template_id": "reminder", "language": "ceb"}, headers=H["worker"]
        ).status_code
        == 422
    )
    # no free-text body field exists on the message endpoint
    r = client.post(
        "/api/cases/C-1/messages", json={"template_id": "sms-minimal", "text": "Take 2 pills"}, headers=H["worker"]
    ).json()
    assert "pills" not in r["message"]["text"]
    assert (
        client.post(
            "/api/cases/C-1/messages", json={"template_id": "sms-minimal"}, headers=H["program_manager"]
        ).status_code
        == 403
    )


def test_clock_advances_and_runs_ladder(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    assert client.post("/api/demo/clock", json={"advance_days": 1}, headers=H["coordinator"]).status_code == 403
    r = client.post("/api/demo/clock", json={"advance_days": 10}, headers=H["supervisor"]).json()
    assert r["offset_days"] == 10 and r["ladder"]["steps_run"] >= 3
    c = client.get("/api/cases/C-1", headers=H["coordinator"]).json()
    assert c["state"] == "escalated" and c["day"] == 10
    assert {"review", "contact", "chw", "supervisor"} <= set(c["ladder_steps"])
    assert client.get("/api/clock", headers=H["worker"]).json()["simulated"] is True


def test_red_flag_flow_over_api(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    r = client.post("/api/cases/C-1/red-flag", json={}, headers=H["worker"])
    assert r.json()["state"] == "human_task_open" and r.json()["automation_paused"]
    assert r.json()["priority"]["tier"] in {"urgent", "high"}
    r = client.post("/api/cases/C-1/transition", json={"target": "resolved_by_human"}, headers=H["worker"])
    assert r.status_code == 403
    r = client.post("/api/cases/C-1/transition", json={"target": "resolved_by_human"}, headers=H["coordinator"])
    assert r.status_code == 200
    r = client.post("/api/cases/C-1/resume-automation", json={"reason": "ok"}, headers=H["coordinator"])
    assert r.status_code == 403
    r = client.post("/api/cases/C-1/resume-automation", json={"reason": "ok"}, headers=H["supervisor"])
    assert r.status_code == 200 and not r.json()["automation_paused"]
    ev = client.get("/api/cases/C-1/events", headers=H["supervisor"]).json()
    assert [e["seq"] for e in ev] == list(range(1, len(ev) + 1))
    assert client.post("/api/admin/cases/C-1/verify-projection", headers=H["supervisor"]).json()["matches"]


def test_csv_validate_and_seed(client):
    csv_text = (
        "record_id,participant_id,screening_type,result,severity,screened_at,language\n"
        "R1,P1,fit,positive,abnormal,2026-10-01,en\nR2,P2,fit,positive,oops,2026-10-01,en\n"
    )
    r = client.post("/api/imports/validate", content=csv_text, headers={**H["coordinator"], "content-type": "text/csv"})
    assert r.json()["summary"]["rows_with_errors"] == 1 and "invalid severity" in r.json()["error_csv"]
    assert client.post("/api/imports/commit", content=csv_text, headers=H["coordinator"]).json()["opened"] == 1
    assert client.post("/api/demo/seed", json={"n": 100}, headers=H["coordinator"]).status_code == 403
    r = client.post("/api/demo/seed", json={"n": 200}, headers=H["supervisor"])
    assert r.json()["data_label"] == "SIMULATED" and r.json()["opened"] > 190
    lst = client.get("/api/cases?limit=200", headers=H["coordinator"]).json()
    assert set(lst["tier_counts"]) >= {"high", "moderate"}
    states = {c["state"] for c in lst["cases"]}
    assert {"new_result", "action_scheduled", "no_show"} <= states
    tiers = [c["priority"]["tier"] for c in lst["cases"] if c["state"] != "closed"]
    rank = {"urgent": 0, "high": 1, "moderate": 2, "routine": 3}
    assert tiers == sorted(tiers, key=rank.get)  # sorted by priority


def test_ai_summary_is_draft_only(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    before = client.get("/api/cases/C-1/events", headers=H["supervisor"]).json()
    r = client.post("/api/ai/cases/C-1/summary", headers=H["coordinator"]).json()
    assert r["label"].startswith("AI draft") and r["mock"]
    assert client.get("/api/cases/C-1/events", headers=H["supervisor"]).json() == before


def test_rate_limit(make_cfg):
    cfg = make_cfg(APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="3")
    c = TestClient(create_app(cfg, MemoryRepository()))
    codes = [c.get("/api/me", headers=H["worker"]).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    assert c.get("/health").status_code == 200


def _fake_verifier(token):
    if token != "good":
        raise ValueError("bad")
    return {"uid": "u1", "role": "supervisor", "email": "s@example.com"}


@pytest.mark.parametrize("demo", ["false", "true"])
def test_real_firebase_auth_always_works(make_cfg, demo):
    cfg = make_cfg(APP_ENV="test", DEMO_MODE=demo)
    c = TestClient(create_app(cfg, MemoryRepository()))
    auth.set_token_verifier(_fake_verifier)
    try:
        assert c.get("/api/me").status_code == 401
        assert c.get("/api/me", headers={"authorization": "Bearer bad"}).status_code == 401
        me = c.get("/api/me", headers={"authorization": "Bearer good"}).json()
        assert me["role"] == "supervisor" and me["demo"] is False
        # a bad token is never rescued by demo headers
        assert c.get("/api/me", headers={"authorization": "Bearer bad", **H["supervisor"]}).status_code == 401
    finally:
        auth.set_token_verifier(None)


def test_demo_headers_ignored_without_demo_mode(make_cfg):
    cfg = make_cfg(APP_ENV="test", DEMO_MODE="false")
    c = TestClient(create_app(cfg, MemoryRepository()))
    assert c.get("/api/me", headers=H["supervisor"]).status_code == 401
    assert c.get("/api/public-config").json()["demo_mode"] is False
    assert c.post("/api/demo/clock", json={"advance_days": 1}).status_code == 401


def test_demo_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    from loopcloser.config import load_config

    assert load_config().demo_mode is False


def test_production_config_is_strict(make_cfg):
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="production", STORAGE_BACKEND="memory")
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="production", STORAGE_BACKEND="firestore", CORS_ORIGINS="*")


def test_removed_settings_are_rejected(make_cfg):
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="test", AUTH_MODE="demo")


def test_mask():
    assert mask_participant("P-000042") == "P-••••42"


def test_seed_is_idempotent_and_bulk(client):
    h = {"x-demo-role": "supervisor"}
    first = client.post("/api/demo/seed", json={"n": 50}, headers=h).json()
    again = client.post("/api/demo/seed", json={"n": 50}, headers=h).json()
    assert first["opened"] > 0 and again["opened"] == 0
    assert again["skipped"] >= first["opened"]
