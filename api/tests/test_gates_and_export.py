"""Pass/hold gates (GATE-1), consent recording, the missing-information demo story (C-DEMO-14), and the
staff-only case downloads (PRIV-2)."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from loopcloser.domain import commands as cmd
from loopcloser.domain import gates
from loopcloser.domain import ladder as ladder_mod
from loopcloser.domain.errors import GuardViolation
from loopcloser.domain.events import AUTOMATION_ACTOR
from loopcloser.domain.states import CaseState as S
from loopcloser.imports.csv_validation import validate_csv
from loopcloser.main import create_app
from loopcloser.store.memory import MemoryRepository
from loopcloser.synth.generator import DEMO_STORIES

from .conftest import NOW, screening
from .test_v2_features import H

CASE = {
    "case_id": "C-G",
    "participant_id": "P-000077",
    "screening_id": "S-G",
    "screening_type": "fit",
    "result": "positive",
    "severity": "abnormal",
    "screened_at": "2026-10-10",
    "owner": "demo-worker-01",
}


@pytest.fixture
def client(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="50000", RATE_LIMIT_SENSITIVE_PER_MINUTE="5000"
    )
    return TestClient(create_app(cfg, MemoryRepository()))


def _gate(view, gid):
    return next(g for g in gates.compute(view) if g["id"] == gid)


# ------------------------------------------------------------------ gate logic


def test_all_gates_pass_on_a_complete_case(repo, lib, coord):
    v = cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner="worker-01",
        now=NOW,
    )
    assert [g["status"] for g in gates.compute(v)] == ["pass"] * 5
    assert gates.holds(v) == [] and gates.blocking(v, "call") == []


def test_missing_consent_phone_and_owner_hold(repo, lib, coord):
    v = cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(contact_consent=None, phone_valid=False),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner=None,
        now=NOW,
    )
    held = {g["id"]: g for g in gates.holds(v)}
    assert set(held) == {"consent", "contact_details", "owner"}
    assert "not recorded" in held["consent"]["detail"] and held["consent"]["missing"]
    assert {g["id"] for g in gates.blocking(v, "call")} == {"consent", "contact_details"}
    assert gates.blocking(v, "chw_visit") == []  # a home visit to ask for consent is still allowed
    assert held["owner"]["blocks"] == []  # warns, does not block


def test_declined_consent_blocks_every_channel(repo, lib, coord):
    v = cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(contact_consent="no"),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner="worker-01",
        now=NOW,
    )
    assert {"call", "sms", "chw_visit"} <= set(_gate(v, "consent")["blocks"])


def test_unknown_consent_value_is_not_recorded(repo, lib, coord):
    v = cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(contact_consent="maybe"),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner="worker-01",
        now=NOW,
    )
    assert v.contact_consent is None and _gate(v, "consent")["status"] == "hold"


def test_record_consent_is_human_logged_and_needs_a_source(repo, lib, coord, worker):
    cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(contact_consent=None),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner="worker-01",
        now=NOW,
    )
    with pytest.raises(GuardViolation) as e:
        cmd.record_consent(repo, "C-1", actor=worker, consent="yes", source="  ", now=NOW)
    assert e.value.rule_id == "GATE-1"
    with pytest.raises(GuardViolation):
        cmd.record_consent(repo, "C-1", actor=AUTOMATION_ACTOR, consent="yes", source="inferred", now=NOW)
    v = cmd.record_consent(repo, "C-1", actor=worker, consent="yes", source="In person at the home visit", now=NOW)
    assert v.contact_consent == "yes" and _gate(v, "consent")["status"] == "pass"
    ev = repo.load_events("C-1")[-1]
    assert ev.type.value == "consent_recorded" and ev.rule_id == "GATE-1" and ev.actor.id == "worker-01"
    assert cmd.rebuild(repo, "C-1").to_doc() == repo.get_case("C-1").to_doc()


def test_ladder_holds_the_sms_reminder_without_consent(repo, lib, coord):
    pw = lib.match("fit", "positive", "abnormal")
    for cid, consent in (("C-YES", "yes"), ("C-NONE", None)):
        cmd.open_case(
            repo,
            case_id=cid,
            screening=screening(contact_consent=consent),
            pathway=pw,
            actor=coord,
            owner="worker-01",
            now=NOW,
        )
        cmd.transition(repo, cid, S.REVIEWED, actor=coord, now=NOW)
    day = NOW.date()
    from datetime import timedelta

    for cid in ("C-YES", "C-NONE"):
        ladder_mod.run_case(repo, cid, today=day + timedelta(days=5), now=NOW + timedelta(days=5))
    sent = lambda cid: [e for e in repo.load_events(cid) if e.type.value == "notification_status"]  # noqa: E731
    assert len(sent("C-YES")) == 1 and sent("C-NONE") == []
    held = [e for e in repo.load_events("C-NONE") if e.type.value == "ladder_step" and e.payload["step"] == "reminder"]
    assert held and "reminder held" in held[0].payload["action"] and held[0].payload["held"] is True
    v = repo.get_case("C-NONE")
    status = {s["id"]: s for s in ladder_mod.status(v, day + timedelta(days=5))}
    assert v.ladder_held == ["reminder"] and "not sent" in status["reminder"]["label"]
    assert "not sent" not in {s["id"]: s for s in ladder_mod.status(repo.get_case("C-YES"), day)}["reminder"]["label"]


def test_recommended_action_asks_for_consent(repo, lib, coord):
    from loopcloser.domain.next_action import recommend

    cmd.open_case(
        repo,
        case_id="C-1",
        screening=screening(contact_consent=None),
        pathway=lib.match("fit", "positive", "abnormal"),
        actor=coord,
        owner="worker-01",
        now=NOW,
    )
    v = cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    assert recommend(v)["kind"] == "consent"


def test_csv_consent_column(repo):
    head = "record_id,participant_id,screening_type,result,severity,screened_at,language,consent\n"
    rep = validate_csv(
        head + "R1,P1,fit,positive,abnormal,2026-10-01,en,yes\n"
        "R2,P2,fit,positive,abnormal,2026-10-01,en,\nR3,P3,fit,positive,abnormal,2026-10-01,en,ok\n"
    )
    r1, r2, r3 = rep.rows
    assert r1.valid and not any("consent" in w for w in r1.warnings)
    assert r2.valid and any("consent to contact not recorded" in w for w in r2.warnings)
    assert not r3.valid and any("invalid consent" in e for e in r3.errors)


# ------------------------------------------------------------------ API: gates block patient contact


def test_api_shows_gates_and_blocks_calls_and_sms(client):
    client.post("/api/cases", json=CASE, headers=H["coordinator"])  # no consent field: not recorded
    c = client.get("/api/cases/C-G", headers=H["worker"]).json()
    assert {g["id"]: g["status"] for g in c["gates"]}["consent"] == "hold"
    assert c["gates_on_hold"] == ["consent"]
    r = client.post(
        "/api/cases/C-G/contact-attempts", json={"channel": "call", "result": "reached"}, headers=H["worker"]
    )
    assert r.status_code == 422 and r.json()["rule_id"] == "GATE-1" and "Consent" in r.json()["detail"]
    r = client.post("/api/cases/C-G/messages", json={"template_id": "reminder", "language": "en"}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "GATE-1"
    # Preview is fine: it shows the text, it does not send anything.
    assert (
        client.post(
            "/api/cases/C-G/messages/preview", json={"template_id": "reminder", "language": "en"}, headers=H["worker"]
        ).status_code
        == 200
    )
    # A community health worker visit is allowed.
    r = client.post(
        "/api/cases/C-G/contact-attempts", json={"channel": "chw_visit", "result": "reached"}, headers=H["worker"]
    )
    assert r.status_code == 200
    # Record consent; then the call goes through.
    assert (
        client.post("/api/cases/C-G/consent", json={"consent": "yes", "source": ""}, headers=H["worker"]).status_code
        == 422
    )
    assert (
        client.post(
            "/api/cases/C-G/consent", json={"consent": "yes", "source": "x"}, headers=H["program_manager"]
        ).status_code
        == 403
    )
    r = client.post(
        "/api/cases/C-G/consent", json={"consent": "yes", "source": "In person at the home visit"}, headers=H["worker"]
    ).json()
    assert r["gates_on_hold"] == [] and r["contact_consent"] == "yes"
    r = client.post(
        "/api/cases/C-G/contact-attempts", json={"channel": "call", "result": "reached"}, headers=H["worker"]
    )
    assert r.status_code == 200


def test_missing_info_story_holds_instead_of_acting(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="50000", RATE_LIMIT_SENSITIVE_PER_MINUTE="5000"
    )
    repo = MemoryRepository()
    client = TestClient(create_app(cfg, repo))
    r = client.post("/api/demo/seed", json={"n": 30}, headers=H["supervisor"]).json()
    assert r["stories"] == len(DEMO_STORIES) == 14
    c = client.get("/api/cases/C-DEMO-14", headers=H["worker"]).json()
    assert c["contact_consent"] is None and c["gates_on_hold"] == ["consent"]
    assert c["recommended_action"]["kind"] == "consent"
    evs = repo.load_events("C-DEMO-14")
    assert not [e for e in evs if e.type.value == "notification_status"]  # no SMS went out
    assert any(e.type.value == "ladder_step" and "held" in e.payload.get("action", "") for e in evs)
    r = client.post(
        "/api/cases/C-DEMO-14/contact-attempts", json={"channel": "call", "result": "reached"}, headers=H["worker"]
    )
    assert r.status_code == 422 and r.json()["rule_id"] == "GATE-1"
    # Every other story records consent, so its gates are unchanged.
    for n in range(1, 14):
        assert client.get(f"/api/cases/C-DEMO-{n:02d}", headers=H["supervisor"]).json()["contact_consent"] == "yes"


# ------------------------------------------------------------------ downloads


def test_exports_are_staff_only_and_logged(client):
    client.post("/api/cases", json=CASE | {"contact_consent": "yes"}, headers=H["coordinator"])
    for kind in ("audit.csv", "audit.json", "summary"):
        assert client.get(f"/api/cases/C-G/export/{kind}", headers=H["patient"]).status_code == 403
    # A worker who does not own the case gets the same answer as for a missing case.
    other = {**H["worker"], "x-demo-user": "demo-worker-99"}
    assert client.get("/api/cases/C-G/export/audit.json", headers=other).status_code == 404

    r = client.get("/api/cases/C-G/export/audit.csv", headers=H["worker"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="C-G-audit-trail.csv"' == r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows[0]["type"] == "case_opened" and rows[0]["content_kind"] == "recorded_fact"
    assert rows[-1]["type"] == "case_exported" and json.loads(rows[-1]["payload"]) == {"kind": "audit_csv"}

    r = client.get("/api/cases/C-G/export/audit.json", headers=H["program_manager"])
    body = r.json()
    assert r.status_code == 200 and body["participant_id"].startswith("P-••••")
    assert set(body["content_kinds"]) == {"recorded_fact", "rule_result", "ai_written"}
    assert "P-000077" not in r.text and "patient_uid" not in r.text  # masked in downloads

    s = client.get("/api/cases/C-G/export/summary", headers=H["coordinator"]).json()
    assert s["recorded_facts"]["contact_consent"] == "yes"
    assert {g["id"] for g in s["rule_results"]["gates"]} == {
        "consent",
        "contact_details",
        "result_on_file",
        "owner",
        "red_flag",
    }
    assert s["rule_results"]["priority"]["score"] >= 0 and s["ai_written"] is None
    kinds = [e["payload"]["kind"] for e in s["timeline"] if e["type"] == "case_exported"]
    assert kinds == ["audit_csv", "audit_json", "summary"]
    # Exports never change the case.
    v = client.get("/api/cases/C-G", headers=H["coordinator"]).json()
    assert v["state"] == "new_result"


def test_ai_draft_is_labeled_ai_written_in_exports(client):
    client.post("/api/cases", json=CASE | {"contact_consent": "yes"}, headers=H["coordinator"])
    assert client.post("/api/ai/cases/C-G/call-prep", headers=H["worker"]).status_code == 200
    rows = client.get("/api/cases/C-G/export/audit.json", headers=H["worker"]).json()["events"]
    assert [e["content_kind"] for e in rows if e["type"] == "ai_draft_created"] == ["ai_written"]
    s = client.get("/api/cases/C-G/export/summary", headers=H["worker"]).json()
    assert s["ai_written"]["label"] and "AI" in s["ai_written"]["label"]
