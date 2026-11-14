"""finalist-v2: demo stories, plain statuses, structured closure evidence, contact reveal, Today filters,
search, dashboard, outbox, and the ladder on vs off comparison."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from loopcloser.domain import commands as cmd
from loopcloser.domain.errors import GuardViolation
from loopcloser.domain.events import Actor
from loopcloser.domain.next_action import lost_contact, plain_status
from loopcloser.domain.roles import Role
from loopcloser.domain.states import CaseState as S
from loopcloser.main import create_app
from loopcloser.store.memory import MemoryRepository
from loopcloser.synth.generator import DEMO_STORIES, story_ids

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


@pytest.fixture
def seeded(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="50000", RATE_LIMIT_SENSITIVE_PER_MINUTE="5000"
    )
    repo = MemoryRepository()
    client = TestClient(create_app(cfg, repo))
    r = client.post("/api/demo/seed", json={"n": 60}, headers=H["supervisor"]).json()
    assert r["stories"] == len(DEMO_STORIES)
    return client, repo


def _open(repo, lib, coord, **kw):
    pw = lib.match("fit", "positive", "abnormal")
    return cmd.open_case(
        repo, case_id="C-1", screening=screening(**kw), pathway=pw, actor=coord, owner="worker-01", now=NOW
    )


# ------------------------------------------------------------------ plain status and lost contact


def test_plain_status_and_lost_contact(repo, lib, coord, worker):
    v = _open(repo, lib, coord)
    assert plain_status(v) == "to_contact" and not lost_contact(v)
    cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    for _ in range(2):
        v = cmd.log_contact_attempt(repo, "C-1", channel="call", result="no_answer", actor=worker, now=NOW)
    assert not lost_contact(v)
    v = cmd.log_contact_attempt(repo, "C-1", channel="call", result="no_answer", actor=worker, now=NOW)
    assert lost_contact(v) and v.state == S.ESCALATED and plain_status(v) == "needs_review"
    # one successful contact means the patient is not lost
    v = cmd.log_contact_attempt(repo, "C-1", channel="call", result="reached", actor=worker, now=NOW)
    assert not lost_contact(v)


def test_plain_status_booked_and_done(repo, lib, coord, worker):
    _open(repo, lib, coord)
    for target, extra in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {"appointment": {"date": "2026-10-20"}}),
    ]:
        v = cmd.transition(repo, "C-1", target, actor=worker, payload=extra, now=NOW)
    assert plain_status(v) == "booked"
    v = cmd.transition(repo, "C-1", S.VISIT_COMPLETED, actor=worker, now=NOW)
    assert plain_status(v) == "done"


# ------------------------------------------------------------------ structured closure evidence (CLOSE-3)


def _to_visit(repo, lib, coord, worker):
    _open(repo, lib, coord)
    for target, extra in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {"appointment": {"date": "2026-10-20"}}),
        (S.VISIT_COMPLETED, {}),
    ]:
        cmd.transition(repo, "C-1", target, actor=worker, payload=extra, now=NOW)


GOOD = {"visit_date": "2026-10-17", "facility": "District hospital", "record_number": "DH-26-0417"}


@pytest.mark.parametrize(
    "bad,msg",
    [
        ({"facility": ""}, "facility"),
        ({"record_number": ""}, "record_number"),
        ({"visit_date": "next week"}, "must be a date"),
        ({"visit_date": "2026-10-18"}, "future"),
        ({"visit_date": "2026-10-01"}, "before the case was opened"),
        ({"record_number": "<script>"}, "Record number"),
        ({"facility": "x" * 121}, "too long"),
    ],
)
def test_structured_evidence_is_validated(repo, lib, coord, worker, bad, msg):
    _to_visit(repo, lib, coord, worker)
    with pytest.raises(GuardViolation) as e:
        cmd.close_case(repo, "C-1", actor=coord, closure_reason="done", evidence=GOOD | bad, now=NOW)
    assert e.value.rule_id == "CLOSE-3" and msg in e.value.message
    assert repo.get_case("C-1").state == S.VISIT_COMPLETED


def test_structured_evidence_is_stored(repo, lib, coord, worker):
    _to_visit(repo, lib, coord, worker)
    v = cmd.close_case(repo, "C-1", actor=coord, closure_reason="done", evidence=GOOD, now=NOW)
    assert v.state == S.CLOSED and v.closure_evidence_detail == GOOD
    assert "DH-26-0417" in v.closure_evidence
    assert repo.load_events("C-1")[-1].rule_id == "CLOSE-3"


def test_close_api_takes_structured_evidence(seeded):
    client, _ = seeded
    url = "/api/cases/C-DEMO-04/close"
    r = client.post(url, json={"closure_reason": "seen"}, headers=H["coordinator"])
    assert r.status_code == 422 and r.json()["rule_id"] == "CLOSE-1"
    future = (date.today() + timedelta(days=30)).isoformat()
    ev = {"visit_date": future, "facility": "RHU", "record_number": "R-1"}
    r = client.post(url, json={"closure_reason": "seen", "evidence": ev}, headers=H["coordinator"])
    assert r.status_code == 422 and r.json()["rule_id"] == "CLOSE-3"
    case = client.get("/api/cases/C-DEMO-04", headers=H["coordinator"]).json()
    appt = case["appointment"]["date"]
    ev = {"visit_date": appt, "facility": "Site A rural health unit", "record_number": "RHU-A 2211"}
    r = client.post(url, json={"closure_reason": "seen", "evidence": ev}, headers=H["coordinator"])
    assert r.status_code == 200 and r.json()["state"] == "closed"
    assert r.json()["closure_evidence_detail"]["record_number"] == "RHU-A 2211"


# ------------------------------------------------------------------ demo stories


def test_lead_story_is_the_whole_loop(seeded):
    client, _ = seeded
    case = client.get("/api/cases/C-DEMO-01", headers=H["supervisor"]).json()
    assert case["state"] == "closed" and case["closure_evidence_detail"]["record_number"] == "DH-26-0417"
    assert case["screening_type"] == "fit" and case["synthetic"]
    ev = client.get("/api/cases/C-DEMO-01/events", headers=H["supervisor"]).json()
    opened = datetime.fromisoformat(ev[0]["at"]).date()
    seq = [(e["type"], e["payload"].get("to") or e["payload"].get("step") or e["payload"].get("result")) for e in ev]
    expected = [
        ("contact_attempt", "no_answer"),
        ("ladder_step", "reminder"),
        ("ladder_step", "chw"),
        ("contact_attempt", "reached"),
        ("state_changed", "action_scheduled"),
        ("state_changed", "visit_completed"),
        ("case_closed", None),
    ]
    it = iter(seq)
    assert all(step in it for step in expected), seq  # in this order
    chw = next(e for e in ev if e["type"] == "ladder_step" and e["payload"]["step"] == "chw")
    assert (datetime.fromisoformat(chw["at"]).date() - opened).days == 7
    visit = next(e for e in ev if e["type"] == "contact_attempt" and e["payload"]["result"] == "reached")
    assert visit["payload"]["channel"] == "chw_visit" and visit["actor"]["id"] == "demo-worker-02"
    now = datetime.now(UTC)
    assert all(datetime.fromisoformat(e["at"]) <= now for e in ev)


def test_story_cases_show_what_they_claim(seeded):
    client, _ = seeded

    def get(n):
        return client.get(f"/api/cases/C-DEMO-{n:02d}", headers=H["supervisor"]).json()

    assert get(2)["red_flag_open"] and get(2)["automation_paused"]
    r = client.post("/api/ai/cases/C-DEMO-02/call-prep", headers=H["coordinator"])
    assert r.status_code == 422 and r.json()["rule_id"] == "AI-2"
    assert get(3)["owner"] is None and get(3)["state"] == "new_result"
    assert get(4)["state"] == "visit_completed"
    assert get(5)["state"] == "escalated" and get(5)["lost_contact"]
    assert get(6)["barriers_open"] == ["transport"]
    assert get(7)["state"] == "no_show"
    assert get(8)["state"] == "closed" and get(8)["signed_off_by"]
    assert any(r["rule_id"] == "PRI-LANGUAGE" for r in get(9)["priority"]["reasons"])
    assert "reminder skipped" in str(client.get("/api/cases/C-DEMO-10/events", headers=H["supervisor"]).json())
    assert get(12)["clinical_urgency"] == "urgent"
    assert get(13)["days_to_due"] == -32 and get(13)["state"] == "escalated"
    # Day 10 for the unowned case: one more day and the ladder hands it to the supervisor
    client.post("/api/demo/clock", json={"advance_days": 1}, headers=H["supervisor"])
    assert get(3)["state"] == "escalated"


def test_stories_are_not_seeded_twice(seeded):
    client, _ = seeded
    again = client.post("/api/demo/seed", json={"n": 60}, headers=H["supervisor"]).json()
    assert again["stories"] == 0 and again["opened"] == 0


def test_story_names_are_fictional_and_ids_unique():
    ids = [story_ids(s)[0] for s in DEMO_STORIES]
    assert len(set(ids)) == len(ids) and 10 <= len(ids) <= 15
    assert sum(1 for s in DEMO_STORIES if s.get("lead")) == 1
    assert all(s["proves"] and s["name"] for s in DEMO_STORIES)


# ------------------------------------------------------------------ contact reveal (PRIV-1)


def test_reveal_contact_is_logged_without_values(seeded):
    client, _ = seeded
    case = client.get("/api/cases/C-DEMO-01", headers=H["worker"]).json()
    assert "Nena" not in str(case)  # never on the case itself
    r = client.post("/api/cases/C-DEMO-01/reveal-contact", json={"fields": ["name"]}, headers=H["worker"]).json()
    assert r["name"] == "Nena Bautista" and "phone" not in r
    ev = client.get("/api/cases/C-DEMO-01/events", headers=H["worker"]).json()[-1]
    assert ev["type"] == "contact_revealed" and ev["payload"] == {"fields": ["name"]}
    assert ev["actor"]["id"] == "demo-worker-01" and ev["rule_id"] == "PRIV-1"
    assert "Nena" not in str(client.get("/api/cases/C-DEMO-01/events", headers=H["worker"]).json())


def test_reveal_contact_permissions(seeded):
    client, _ = seeded
    assert client.post("/api/cases/C-DEMO-01/reveal-contact", json={}, headers=H["program_manager"]).status_code == 403
    other = {**H["worker"], "x-demo-user": "demo-worker-99"}
    assert client.post("/api/cases/C-DEMO-01/reveal-contact", json={}, headers=other).status_code == 404
    bad = client.post("/api/cases/C-DEMO-01/reveal-contact", json={"fields": ["address"]}, headers=H["coordinator"])
    assert bad.status_code == 422 and bad.json()["rule_id"] == "PRIV-1"


def test_reveal_needs_a_simulated_contact(seeded):
    client, _ = seeded
    case = {
        "case_id": "C-REAL",
        "participant_id": "P-777777",
        "screening_id": "S-R",
        "screening_type": "fit",
        "result": "positive",
        "severity": "abnormal",
        "screened_at": "2026-10-10",
        "owner": "demo-worker-01",
    }
    client.post("/api/cases", json=case, headers=H["coordinator"])
    assert client.post("/api/cases/C-REAL/reveal-contact", json={}, headers=H["coordinator"]).status_code == 404


def test_contact_reveal_guard(repo, lib, coord):
    _open(repo, lib, coord)
    pm = Actor(id="pm", role=Role.PROGRAM_MANAGER)
    with pytest.raises(GuardViolation):
        cmd.record_contact_reveal(repo, "C-1", actor=pm, fields=("name",), now=NOW)
    v = cmd.record_contact_reveal(repo, "C-1", actor=coord, fields=("phone",), now=NOW)
    assert v.state == S.NEW_RESULT  # audit only


# ------------------------------------------------------------------ Today filters, summary, search


def test_today_summary_and_filters(seeded):
    client, _ = seeded
    t = client.get("/api/today", headers=H["supervisor"]).json()
    s = t["summary"]
    assert set(s) == {"to_contact", "overdue", "lost_contact", "needs_review"}
    assert s["overdue"] == t["lanes"]["overdue"]["count"] and s["lost_contact"] >= 1
    cases = [c for lane in t["lanes"].values() for c in lane["cases"]]
    assert all(c["plain_status_label"] in {"To contact", "Booked", "Needs review", "Done"} for c in cases)
    mine = client.get("/api/today?mine=true", headers=H["coordinator"]).json()
    mine_cases = [c for lane in mine["lanes"].values() for c in lane["cases"]]
    assert mine_cases and all("demo-coord-01" in (c["owner"], c.get("backup_owner")) for c in mine_cases)
    assert mine["total"] < t["total"]
    fit = client.get("/api/today?screening_type=fit", headers=H["supervisor"]).json()
    assert all(c["screening_type"] == "fit" for lane in fit["lanes"].values() for c in lane["cases"])
    assert 0 < fit["total"] < t["total"]
    assert client.get("/api/today?screening_type=xray", headers=H["supervisor"]).status_code == 400


def test_search_by_case_id_respects_scope(seeded):
    client, _ = seeded
    r = client.get("/api/cases/search?q=demo-01", headers=H["coordinator"]).json()
    assert [c["id"] for c in r["cases"]] == ["C-DEMO-01"]
    # a worker only finds cases assigned to them
    w = client.get("/api/cases/search?q=DEMO", headers=H["worker"]).json()["cases"]
    assert w and all(c["owner"] == "demo-worker-01" for c in w)
    assert client.get("/api/cases/search?q=DEMO", headers=H["patient"]).status_code == 403


# ------------------------------------------------------------------ dashboard and outbox


def test_dashboard_numbers_come_from_the_cases(seeded):
    client, repo = seeded
    assert client.get("/api/dashboard", headers=H["worker"]).status_code == 403
    d = client.get("/api/dashboard", headers=H["program_manager"]).json()
    cases = repo.list_cases()
    closed = [v for v in cases if v.state == S.CLOSED]
    assert d["total_cases"] == len(cases) and d["closed"] == len(closed) >= 2
    assert d["closure_rate"] == round(len(closed) / len(cases), 3)
    # two story cases reached a visit: Day 11 (lead) and Day 5 (Jun Mercado), so the median is 8 days
    assert d["days_to_care_n"] == 2 and d["median_days_to_care"] == 8
    assert d["lost_to_follow_up"] == sum(1 for v in cases if v.state != S.CLOSED and lost_contact(v))
    assert sum(d["by_status"].values()) == len(cases)


def test_outbox_shows_the_patient_sms(seeded):
    client, _ = seeded
    r = client.get("/api/cases/C-DEMO-01/outbox", headers=H["coordinator"]).json()
    assert [m["template_id"] for m in r["messages"]] == ["reminder", "booking-confirmation"]
    assert r["messages"][0]["by_automation"] and r["messages"][0]["language"] == "fil"
    assert all(m["text"] for m in r["messages"]) and r["simulated"]
    assert client.get("/api/cases/C-DEMO-01/outbox", headers=H["program_manager"]).status_code == 403


# ------------------------------------------------------------------ ladder on vs off (small cohort)


def test_ladder_compare_small_cohort():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "eval" / "run_eval.py"
    spec = importlib.util.spec_from_file_location("run_eval", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.ladder_compare(n=120, seed=7)
    on, off = r["ladder_on"], r["ladder_off"]
    assert on["unaccountable"] == 0 and on["silently_overdue"] == 0
    assert off["unaccountable"] > 0 and off["silently_overdue"] > 0
    assert on["unowned"] == off["unowned"] and on["overdue"] == off["overdue"]
    assert on["red_flag_touched_by_automation"] == 0
