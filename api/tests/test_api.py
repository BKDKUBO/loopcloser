import pytest
from fastapi.testclient import TestClient

from loopcloser import auth
from loopcloser.config import ConfigError
from loopcloser.main import create_app, mask_participant
from loopcloser.store.memory import MemoryRepository

H = {
    r: {"x-demo-role": r, "x-demo-user": u}
    for r, u in [
        ("coordinator", "coord-01"),
        ("worker", "worker-01"),
        ("supervisor", "sup-01"),
        ("program_manager", "pm-01"),
        ("patient", "patient-01"),
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
    "owner": "worker-01",
}


@pytest.fixture
def client(make_cfg):
    cfg = make_cfg(APP_ENV="test", AUTH_MODE="demo", RATE_LIMIT_PER_MINUTE="1000")
    return TestClient(create_app(cfg, MemoryRepository()))


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["checks"]["pathways"] == 6
    assert "x-request-id" in r.headers


def test_requires_role(client):
    assert client.get("/api/me").status_code == 403
    assert client.get("/api/me", headers={"x-demo-role": "admin"}).status_code == 403
    assert client.get("/api/me", headers=H["worker"]).json()["role"] == "worker"


def test_role_permissions(client):
    assert client.post("/api/cases", json=CASE, headers=H["worker"]).status_code == 403
    assert client.post("/api/cases", json=CASE, headers=H["program_manager"]).status_code == 403
    r = client.post("/api/cases", json=CASE, headers=H["coordinator"])
    assert r.status_code == 201
    body = r.json()
    assert body["participant_id"] == "P-••••42" and "patient_uid" not in body
    # worker sees only assigned cases, patient sees none of these
    assert client.get("/api/cases", headers=H["worker"]).json()["total"] == 1
    assert client.get("/api/cases", headers={**H["worker"], "x-demo-user": "worker-99"}).json()["total"] == 0
    assert client.get("/api/cases/C-1", headers=H["patient"]).status_code == 404
    assert client.get("/api/cases", headers=H["program_manager"]).json()["total"] == 1
    # program manager cannot act
    r = client.post("/api/cases/C-1/transition", json={"target": "reviewed"}, headers=H["program_manager"])
    assert r.status_code == 403


def test_guard_violation_returns_rule_id(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    r = client.post("/api/cases/C-1/transition", json={"target": "action_scheduled"}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "SM-1"
    r = client.post("/api/cases/C-1/close", json={"closure_reason": "x", "sign_off": True}, headers=H["worker"])
    assert r.status_code == 403


def test_red_flag_flow_over_api(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    r = client.post("/api/cases/C-1/red-flag", json={}, headers=H["worker"])
    assert r.json()["state"] == "human_task_open" and r.json()["automation_paused"]
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
    v = client.post("/api/admin/cases/C-1/verify-projection", headers=H["supervisor"]).json()
    assert v["matches"]


def test_csv_validate_and_seed(client):
    csv_text = (
        "record_id,participant_id,screening_type,result,severity,screened_at,language\n"
        "R1,P1,fit,positive,abnormal,2026-10-01,en\nR2,P2,fit,positive,oops,2026-10-01,en\n"
    )
    r = client.post("/api/imports/validate", content=csv_text, headers={**H["coordinator"], "content-type": "text/csv"})
    assert r.json()["summary"]["rows_with_errors"] == 1 and "invalid severity" in r.json()["error_csv"]
    r = client.post("/api/imports/commit", content=csv_text, headers=H["coordinator"])
    assert r.json()["opened"] == 1
    assert client.post("/api/demo/seed", json={"n": 100}, headers=H["coordinator"]).status_code == 403
    r = client.post("/api/demo/seed", json={"n": 100}, headers=H["supervisor"])
    assert r.json()["data_label"] == "SIMULATED" and r.json()["opened"] > 90


def test_ai_summary_is_draft_only(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])
    before = client.get("/api/cases/C-1/events", headers=H["supervisor"]).json()
    r = client.post("/api/ai/cases/C-1/summary", headers=H["coordinator"]).json()
    assert r["label"].startswith("AI draft") and r["mock"]
    assert client.get("/api/cases/C-1/events", headers=H["supervisor"]).json() == before


def test_rate_limit(make_cfg):
    cfg = make_cfg(APP_ENV="test", AUTH_MODE="demo", RATE_LIMIT_PER_MINUTE="3")
    c = TestClient(create_app(cfg, MemoryRepository()))
    codes = [c.get("/api/me", headers=H["worker"]).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    assert c.get("/health").status_code == 200  # health is never limited


def test_firebase_mode_verifies_tokens(make_cfg):
    cfg = make_cfg(APP_ENV="test", AUTH_MODE="firebase")
    from loopcloser import config as config_mod

    config_mod.get_config.cache_clear()
    c = TestClient(create_app(cfg, MemoryRepository()))

    def fake(token):
        if token != "good":
            raise ValueError("bad")
        return {"uid": "u1", "role": "supervisor", "email": "s@example.com"}

    auth.set_token_verifier(fake)
    try:
        assert c.get("/api/me").status_code == 401
        assert c.get("/api/me", headers={"authorization": "Bearer bad"}).status_code == 401
        assert c.get("/api/me", headers=H["supervisor"]).status_code == 401  # demo headers ignored
        assert c.get("/api/me", headers={"authorization": "Bearer good"}).json()["role"] == "supervisor"
    finally:
        auth.set_token_verifier(None)
        config_mod.get_config.cache_clear()


def test_production_config_is_strict(make_cfg):
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="production", AUTH_MODE="demo", STORAGE_BACKEND="firestore")
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="production", AUTH_MODE="firebase", STORAGE_BACKEND="memory")
    with pytest.raises(ConfigError):
        make_cfg(APP_ENV="production", AUTH_MODE="firebase", STORAGE_BACKEND="firestore", CORS_ORIGINS="*")


def test_mask():
    assert mask_participant("P-000042") == "P-••••42"
