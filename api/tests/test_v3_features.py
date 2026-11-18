"""feedback-v3: FHIR R4 Bundle import, simulated patient SMS replies (MSG-4), and the auto-refresh change counter."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from loopcloser.domain import commands as cmd
from loopcloser.domain import gates
from loopcloser.domain import ladder as ladder_mod
from loopcloser.domain.errors import GuardViolation
from loopcloser.domain.states import CaseState as S
from loopcloser.fhir import importer as fhir
from loopcloser.main import create_app
from loopcloser.store.memory import MemoryRepository

from .conftest import NOW, screening

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
TODAY = date(2026, 10, 17)


@pytest.fixture
def client(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="50000", RATE_LIMIT_SENSITIVE_PER_MINUTE="5000"
    )
    return TestClient(create_app(cfg, MemoryRepository()))


# ------------------------------------------------------------------ FHIR mapping


@pytest.mark.parametrize(
    "kind,stype,result", [("fit", "fit", "positive"), ("cervical", "cervical", "positive"), ("bp", "bp", "elevated")]
)
def test_sample_bundles_map_to_one_case_each(kind, stype, result):
    plan = fhir.plan_import(fhir.sample_bundle(kind, today=TODAY, seed="AB12"), today=TODAY)
    assert plan.synthetic and not plan.warnings
    assert len(plan.items) == 1  # the Observation inside the report is not a second case
    m = plan.items[0]
    assert m.status == "ready" and m.resource.startswith("DiagnosticReport/")
    assert m.screening["screening_type"] == stype and m.screening["result"] == result
    assert m.screening["contact_consent"] is None  # never inferred (GATE-1)
    assert m.screening["participant_id"] == "FHIR-SIM-AB12" and m.screening["phone_valid"]
    assert m.screening["language"] == "fil" and m.referral
    dumped = json.dumps(m.screening) + json.dumps(m.source)
    assert "SIMULATED Patient" not in dumped and "+639000199999" not in dumped  # no name or phone kept


def _bundle(**obs_overrides):
    b = fhir.sample_bundle("fit", today=TODAY, seed="X1")
    b["entry"] = [e for e in b["entry"] if e["resource"]["resourceType"] in {"Patient", "Observation"}]
    obs = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation")
    for k, v in obs_overrides.items():
        if v is None:
            obs.pop(k, None)
        else:
            obs[k] = v
    return b


def test_fhir_rules_for_status_interpretation_and_dates():
    def one(**kw):
        return fhir.plan_import(_bundle(**kw), today=TODAY).items[0]

    assert one().status == "ready"  # a lone Observation is imported too
    assert one(status="preliminary").status == "skipped"
    neg = [{"coding": [{"system": fhir.V3_INTERP, "code": "NEG"}]}]
    assert one(interpretation=neg).status == "skipped"
    m = one(interpretation=None)
    assert m.status == "error" and "does not interpret raw values" in m.messages[0]
    assert one(effectiveDateTime=(TODAY + timedelta(days=3)).isoformat()).status == "error"
    crit = [{"coding": [{"system": fhir.V3_INTERP, "code": "HH"}]}]
    assert one(interpretation=crit).screening["severity"] == "critical"
    other = {"coding": [{"system": fhir.LOINC, "code": "2345-7", "display": "Glucose"}]}
    m = one(code=other)
    assert (
        m.status == "ready" and m.screening["screening_type"] == "generic" and "not in the LOINC table" in m.messages[0]
    )


@pytest.mark.parametrize(
    "bad,msg",
    [
        ({"resourceType": "Patient"}, "Bundle"),
        ({"resourceType": "Bundle", "type": "nonsense", "entry": []}, "Bundle.type"),
        ({"resourceType": "Bundle", "type": "collection", "entry": []}, "no entries"),
        (
            {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": {"resourceType": "Patient"}}]},
            "Observation or DiagnosticReport",
        ),
    ],
)
def test_unreadable_bundles_are_refused(bad, msg):
    with pytest.raises(fhir.BundleError) as e:
        fhir.plan_import(bad, today=TODAY)
    assert msg in str(e.value)


def test_untagged_bundle_warns_and_is_not_synthetic():
    b = _bundle()
    b.pop("meta")
    plan = fhir.plan_import(b, today=TODAY)
    assert not plan.synthetic and "synthetic" in plan.warnings[0]


# ------------------------------------------------------------------ FHIR API


def test_fhir_import_api_opens_a_case_with_consent_on_hold(client):
    sample = client.get("/api/fhir/sample?kind=fit", headers=H["coordinator"]).json()
    r = client.post("/api/fhir/import/validate", json=sample, headers=H["coordinator"])
    assert r.status_code == 200 and r.json()["items"][0]["status"] == "ready"
    r = client.post("/api/fhir/import", json={"bundle": sample}, headers=H["coordinator"])
    assert r.status_code == 200, r.text
    body = r.json()
    case = body["opened"][0]
    assert case["state"] == "new_result" and case["screening_type"] == "fit" and case["contact_consent"] is None
    assert case["source"]["kind"] == "fhir_r4_bundle" and case["source"]["code"] == "LOINC 29771-3"
    assert case["data_label"] == "SIMULATED" and "consent" in case["gates_on_hold"]
    # Calls and SMS hold until a person records consent.
    r = client.post(
        f"/api/cases/{case['id']}/contact-attempts",
        json={"channel": "call", "result": "reached"},
        headers=H["coordinator"],
    )
    assert r.status_code == 422 and r.json()["rule_id"] == "GATE-1"
    # Importing the same Bundle again opens nothing.
    again = client.post("/api/fhir/import", json=sample, headers=H["coordinator"]).json()
    assert again["opened"] == [] and again["items"][0]["status"] == "skipped"
    events = client.get(f"/api/cases/{case['id']}/events", headers=H["supervisor"]).text
    assert "SIMULATED Patient" not in events and "+639000199999" not in events


def test_fhir_routes_are_coordinator_and_supervisor_only(client):
    sample = client.get("/api/fhir/sample", headers=H["supervisor"]).json()
    for role in ("worker", "program_manager", "patient"):
        assert client.get("/api/fhir/sample", headers=H[role]).status_code == 403
        assert client.post("/api/fhir/import", json=sample, headers=H[role]).status_code == 403
        assert client.post("/api/fhir/import/validate", json=sample, headers=H[role]).status_code == 403


def test_fhir_api_errors_are_clear(client):
    r = client.post("/api/fhir/import", content=b"{not json", headers=H["coordinator"])
    assert r.status_code == 422 and "JSON" in r.json()["detail"]
    r = client.post("/api/fhir/import", json={"resourceType": "Patient"}, headers=H["coordinator"])
    assert r.status_code == 422 and "Bundle" in r.json()["detail"]
    big = b'{"resourceType":"Bundle","pad":"' + b"x" * (fhir.MAX_BYTES + 1) + b'"}'
    assert client.post("/api/fhir/import", content=big, headers=H["coordinator"]).status_code == 413
    assert client.get("/api/fhir/sample?kind=xray", headers=H["coordinator"]).status_code == 400


# ------------------------------------------------------------------ SMS replies (MSG-4)


def _texted(repo, lib, coord, *, to=S.REVIEWED):
    pw = lib.match("fit", "positive", "abnormal")
    cmd.open_case(repo, case_id="C-1", screening=screening(), pathway=pw, actor=coord, owner="worker-01", now=NOW)
    cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    cmd.record_notification(
        repo,
        "C-1",
        status="sent",
        channel="sms",
        template_id="result-notice",
        template_version="1.0.0",
        language="en",
        actor=coord,
        now=NOW,
    )
    path = [
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {"appointment": {"date": "2026-10-25", "clinic": "Site A"}}),
    ]
    for target, payload in path:
        if repo.get_case("C-1").state == to:
            break
        cmd.transition(repo, "C-1", target, actor=coord, payload=payload, now=NOW)
    return repo.get_case("C-1")


def test_yes_notifies_but_never_confirms_understanding(repo, lib, coord):
    _texted(repo, lib, coord)
    v = cmd.record_sms_reply(repo, "C-1", keyword="yes", entered_by=coord, now=NOW)
    assert v.state == S.PATIENT_NOTIFIED and v.last_sms_reply["keyword"] == "YES"  # MSG-1: not understood
    ev = [e for e in repo.load_events("C-1") if e.type.value == "sms_reply_received"][0]
    assert (
        ev.actor.id == "patient-sms (simulated)" and ev.payload["entered_by"] == "coord-01" and ev.payload["simulated"]
    )


def test_yes_confirms_a_booked_appointment(repo, lib, coord):
    _texted(repo, lib, coord, to=S.ACTION_SCHEDULED)
    v = cmd.record_sms_reply(repo, "C-1", keyword="YES", entered_by=coord, now=NOW)
    assert v.state == S.ACTION_SCHEDULED and v.appointment["confirmed_by_patient"]


def test_resched_moves_a_booking_to_rescheduled(repo, lib, coord):
    _texted(repo, lib, coord, to=S.ACTION_SCHEDULED)
    v = cmd.record_sms_reply(repo, "C-1", keyword="RESCHED", entered_by=coord, now=NOW)
    assert v.state == S.RESCHEDULED and "reschedule" in v.next_action.lower()


def test_stop_opts_out_of_sms_and_is_respected(repo, lib, coord):
    _texted(repo, lib, coord)
    v = cmd.record_sms_reply(repo, "C-1", keyword="STOP", entered_by=coord, now=NOW)
    assert v.sms_opt_out and v.state == S.REVIEWED
    gate = next(g for g in gates.compute(v) if g["id"] == "sms_opt_out")
    assert gate["status"] == "hold" and gate["blocks"] == ["sms"]
    assert gates.blocking(v, "sms") and not any(g["id"] == "sms_opt_out" for g in gates.blocking(v, "call"))
    with pytest.raises(GuardViolation) as e:
        cmd.record_notification(
            repo,
            "C-1",
            status="sent",
            channel="sms",
            template_id="reminder",
            template_version="1.0.0",
            language="en",
            actor=coord,
            now=NOW,
        )
    assert e.value.rule_id == "MSG-4"
    # The automatic SMS reminder is held, not sent.
    ladder_mod.run_case(repo, "C-1", today=TODAY + timedelta(days=10), now=NOW)
    sent = [e for e in repo.load_events("C-1") if e.type.value == "notification_status"]
    assert len(sent) == 1
    assert "reminder" in repo.get_case("C-1").ladder_held


def test_replies_need_a_text_and_an_open_case(repo, lib, coord):
    pw = lib.match("fit", "positive", "abnormal")
    cmd.open_case(repo, case_id="C-2", screening=screening(), pathway=pw, actor=coord, owner="w", now=NOW)
    with pytest.raises(GuardViolation) as e:
        cmd.record_sms_reply(repo, "C-2", keyword="YES", entered_by=coord, now=NOW)
    assert e.value.rule_id == "MSG-4"
    _texted(repo, lib, coord)
    with pytest.raises(GuardViolation):
        cmd.record_sms_reply(repo, "C-1", keyword="MAYBE", entered_by=coord, now=NOW)


def test_red_flag_case_only_logs_the_reply(repo, lib, coord):
    _texted(repo, lib, coord, to=S.ACTION_SCHEDULED)
    cmd.report_red_flag(repo, "C-1", actor=coord, source="staff", code="severe_headache", now=NOW)
    before = repo.get_case("C-1").state
    v = cmd.record_sms_reply(repo, "C-1", keyword="RESCHED", entered_by=coord, now=NOW)
    assert v.state == before and v.red_flag_open


def test_sms_reply_api_and_outbox(client):
    c = {
        "case_id": "C-9",
        "participant_id": "P-000009",
        "screening_id": "S-9",
        "screening_type": "fit",
        "result": "positive",
        "severity": "abnormal",
        "screened_at": "2026-10-10",
        "owner": "demo-worker-01",
        "contact_consent": "yes",
    }
    assert client.post("/api/cases", json=c, headers=H["coordinator"]).status_code == 201
    client.post("/api/cases/C-9/transition", json={"target": "reviewed"}, headers=H["coordinator"])
    r = client.post("/api/cases/C-9/sms-replies", json={"keyword": "YES"}, headers=H["coordinator"])
    assert r.status_code == 422 and r.json()["rule_id"] == "MSG-4"  # nothing was texted yet
    body = {"template_id": "result-notice", "language": "en", "channel": "sms"}
    assert client.post("/api/cases/C-9/messages", json=body, headers=H["coordinator"]).status_code == 200
    assert (
        client.post("/api/cases/C-9/sms-replies", json={"keyword": "NO"}, headers=H["coordinator"]).status_code == 422
    )
    assert (
        client.post("/api/cases/C-9/sms-replies", json={"keyword": "YES"}, headers=H["program_manager"]).status_code
        == 403
    )
    r = client.post("/api/cases/C-9/sms-replies", json={"keyword": "STOP"}, headers=H["worker"])
    assert r.status_code == 200 and r.json()["sms_opt_out"]
    assert "sms_opt_out" in r.json()["gates_on_hold"]
    r = client.post("/api/cases/C-9/messages", json=body, headers=H["coordinator"])
    assert r.status_code == 422 and r.json()["rule_id"] in {"GATE-1", "MSG-4"}
    o = client.get("/api/cases/C-9/outbox", headers=H["coordinator"]).json()
    assert [m["direction"] for m in o["messages"]] == ["out", "in"] and o["messages"][1]["text"] == "STOP"
    assert o["sms_opt_out"] and o["can_reply"]


def test_sms_replies_are_demo_only(make_cfg):
    cfg = make_cfg(APP_ENV="test", DEMO_MODE="false", RATE_LIMIT_PER_MINUTE="5000")
    c = TestClient(create_app(cfg, MemoryRepository()))
    r = c.post("/api/cases/C-1/sms-replies", json={"keyword": "YES"}, headers=H["coordinator"])
    assert r.status_code in {401, 403}


# ------------------------------------------------------------------ auto-refresh counter


def test_changes_counter_moves_on_writes_only(client):
    v0 = client.get("/api/changes", headers=H["worker"]).json()["version"]
    client.get("/api/today", headers=H["coordinator"])
    assert client.get("/api/changes", headers=H["worker"]).json()["version"] == v0
    sample = client.get("/api/fhir/sample", headers=H["coordinator"]).json()
    client.post("/api/fhir/import", json=sample, headers=H["coordinator"])
    assert client.get("/api/changes", headers=H["worker"]).json()["version"] != v0
    assert client.get("/api/changes").status_code == 401


# ------------------------------------------------------------------ simulated slots and booking (APPT-1, APPT-2)


def _today():
    """The API's today is the Manila date (CI runs in UTC)."""
    from datetime import UTC, datetime

    from loopcloser.domain.localtime import local_date

    return local_date(datetime.now(UTC))


def _ready_to_book(client, cid="C-B1"):
    c = {
        "case_id": cid,
        "participant_id": "P-000077",
        "screening_id": "S-77",
        "screening_type": "bp",
        "result": "elevated",
        "severity": "abnormal",
        "screened_at": _today().isoformat(),
        "owner": "demo-worker-01",
        "contact_consent": "yes",
    }
    assert client.post("/api/cases", json=c, headers=H["coordinator"]).status_code == 201
    for t, extra in [
        ("reviewed", {}),
        ("patient_notified", {}),
        ("understanding_confirmed", {"source": "staff_confirmed"}),
    ]:
        assert (
            client.post(f"/api/cases/{cid}/transition", json={"target": t, **extra}, headers=H["worker"]).status_code
            == 200
        )


def test_slots_are_weekdays_in_the_next_14_days(client):
    _ready_to_book(client)
    r = client.get("/api/cases/C-B1/slots", headers=H["worker"]).json()
    assert r["label"].startswith("Simulated slots") and r["clinic"] in {c["id"] for c in r["clinics"]}
    days = {date.fromisoformat(s["date"]) for s in r["slots"]}
    assert days and all(d.weekday() < 5 and _today() < d <= _today() + timedelta(days=14) for d in days)
    assert all(s["free"] == 2 and s["time"] in {"09:00", "10:00", "11:00", "14:00"} for s in r["slots"])
    assert client.get("/api/cases/C-B1/slots?clinic=NOPE", headers=H["worker"]).status_code == 400
    assert client.get("/api/cases/C-B1/slots", headers=H["program_manager"]).status_code == 403


def test_booking_a_slot_stores_a_fhir_shaped_appointment_and_counts_capacity(client):
    for cid in ("C-B1", "C-B2", "C-B3"):
        _ready_to_book(client, cid)
    slot = client.get("/api/cases/C-B1/slots?clinic=SITE-A", headers=H["worker"]).json()["slots"][0]
    r = client.post("/api/cases/C-B1/appointments", json={"slot_id": slot["slot_id"]}, headers=H["worker"])
    assert r.status_code == 200, r.text
    case = r.json()
    appt = case["appointment"]
    assert case["state"] == "action_scheduled" and appt["slot_id"] == slot["slot_id"] and appt["simulated"]
    assert appt["fhir"]["resourceType"] == "Appointment" and appt["fhir"]["status"] == "booked"
    assert appt["fhir"]["start"].endswith("+08:00") and "P-••••" in json.dumps(appt["fhir"], ensure_ascii=False)
    assert "P-000077" not in json.dumps(appt)
    assert (
        client.post("/api/cases/C-B2/appointments", json={"slot_id": slot["slot_id"]}, headers=H["worker"]).status_code
        == 200
    )
    left = client.get("/api/cases/C-B3/slots?clinic=SITE-A", headers=H["worker"]).json()["slots"][0]
    assert left["slot_id"] == slot["slot_id"] and left["free"] == 0
    r = client.post("/api/cases/C-B3/appointments", json={"slot_id": slot["slot_id"]}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "APPT-2"
    # Rescheduling frees the place.
    client.post(
        "/api/cases/C-B1/transition", json={"target": "rescheduled", "reason": "patient asked"}, headers=H["worker"]
    )
    assert (
        client.post("/api/cases/C-B3/appointments", json={"slot_id": slot["slot_id"]}, headers=H["worker"]).status_code
        == 200
    )


def test_booking_refuses_unoffered_slots_and_follows_the_state_machine(client):
    _ready_to_book(client)
    saturday = _today() + timedelta(days=(5 - _today().weekday()) % 7 or 7)
    for bad in (
        f"SITE-A|{saturday.isoformat()}T09:00",
        "SITE-A|2020-01-06T09:00",
        "SITE-A|garbage",
        f"MOON|{(_today() + timedelta(days=1)).isoformat()}T09:00",
    ):
        r = client.post("/api/cases/C-B1/appointments", json={"slot_id": bad}, headers=H["worker"])
        assert r.status_code == 422 and r.json()["rule_id"] == "APPT-1", bad
    c = {
        "case_id": "C-B9",
        "participant_id": "P-000078",
        "screening_id": "S-78",
        "screening_type": "bp",
        "result": "elevated",
        "severity": "abnormal",
        "screened_at": _today().isoformat(),
        "owner": "demo-worker-01",
    }
    client.post("/api/cases", json=c, headers=H["coordinator"])
    slot = client.get("/api/cases/C-B9/slots", headers=H["worker"]).json()["slots"][0]["slot_id"]
    r = client.post("/api/cases/C-B9/appointments", json={"slot_id": slot}, headers=H["worker"])
    assert r.status_code == 422 and r.json()["rule_id"] == "SM-1"  # new result: not ready to book


# ------------------------------------------------------------------ attendance (drop-off) risk, read time only

from loopcloser.domain import risk  # noqa: E402


def _case(repo, lib, coord, cid="C-R", **kw):
    pw = lib.match("fit", "positive", "abnormal")
    return cmd.open_case(repo, case_id=cid, screening=screening(**kw), pathway=pw, actor=coord, owner="w", now=NOW)


def test_risk_rules_add_up_to_levels(repo, lib, coord, worker):
    v = _case(repo, lib, coord)
    assert risk.compute(v, TODAY)["level"] == "none"
    cmd.transition(repo, "C-R", S.REVIEWED, actor=coord, now=NOW)
    for _ in range(2):
        cmd.log_contact_attempt(repo, "C-R", channel="call", result="no_answer", actor=worker, now=NOW)
    r = risk.compute(repo.get_case("C-R"), TODAY)
    assert [x["rule_id"] for x in r["reasons"]] == ["RISK-FAILED"] and r["level"] == "none"
    cmd.report_barrier(repo, "C-R", actor=worker, barrier="transport", now=NOW)
    r = risk.compute(repo.get_case("C-R"), TODAY)
    assert r["points"] == 4 and r["level"] == "watch"
    assert any("ride" in x["help"] for x in r["reasons"] if x["rule_id"] == "RISK-BARRIER")
    for b in ("cost", "fear"):
        cmd.report_barrier(repo, "C-R", actor=worker, barrier=b, now=NOW)
    r = risk.compute(repo.get_case("C-R"), TODAY)
    assert sum(x["points"] for x in r["reasons"] if x["rule_id"] == "RISK-BARRIER") == 4  # capped
    assert r["level"] == "high" and r["points"] == 6
    # the deadline rule: due 2026-11-09 (screened 10-10 + 30 days)
    late = risk.compute(repo.get_case("C-R"), date(2026, 11, 5))
    assert any(x["rule_id"] == "RISK-DEADLINE" for x in late["reasons"])


def test_risk_excludes_red_flag_closed_and_declined(repo, lib, coord, supervisor):
    v = _case(repo, lib, coord, phone_valid=False)
    assert risk.compute(v, TODAY)["points"] == 2  # RISK-NO-PHONE
    cmd.report_red_flag(repo, "C-R", actor=coord, source="staff", code="x", now=NOW)
    assert risk.compute(repo.get_case("C-R"), TODAY) == {"level": "none", "points": 0, "reasons": [], "excluded": True}
    v = _case(repo, lib, coord, cid="C-D", contact_consent="no", phone_valid=False)
    assert all(x["rule_id"] != "RISK-CONSENT" for x in risk.compute(v, TODAY)["reasons"])  # consent is never scored


def test_risk_shows_for_staff_with_its_rule_table(client):
    c = {
        "case_id": "C-R1",
        "participant_id": "P-000099",
        "screening_id": "S-99",
        "screening_type": "fit",
        "result": "positive",
        "severity": "abnormal",
        "screened_at": "2026-10-10",
        "owner": "demo-worker-01",
        "contact_consent": "yes",
        "barriers": ["transport", "cost"],
    }
    client.post("/api/cases", json=c, headers=H["coordinator"])
    staff = client.get("/api/cases/C-R1", headers=H["coordinator"]).json()
    assert staff["attendance_risk"]["level"] in {"watch", "high"}
    rules = client.get("/api/risk/rules", headers=H["worker"]).json()
    assert rules["levels"] == {"watch": 3, "high": 6} and "not a validated prediction" in rules["note"]
