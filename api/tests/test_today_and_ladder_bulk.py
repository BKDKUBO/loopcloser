"""Today view queries and the bulk escalation ladder: same answers as reading every case, far less work."""

from collections import Counter
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from loopcloser.domain import commands as cmd
from loopcloser.domain import indexing as idx
from loopcloser.domain import ladder
from loopcloser.domain import priority as prio
from loopcloser.domain.states import CaseState as S
from loopcloser.main import create_app
from loopcloser.store.memory import MemoryRepository

from .conftest import NOW, screening

SUP = {"x-demo-role": "supervisor", "x-demo-user": "demo-sup-01"}
WORKER = {"x-demo-role": "worker", "x-demo-user": "demo-worker-01"}


@pytest.fixture
def setup(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="5000", RATE_LIMIT_SENSITIVE_PER_MINUTE="500"
    )
    repo = MemoryRepository()
    client = TestClient(create_app(cfg, repo))
    assert client.post("/api/demo/seed", json={"n": 300}, headers=SUP).json()["opened"] > 290
    return cfg, repo, client


def _brute(repo, today: date, person: str | None = None):
    """The old way: read every case and compute lanes and tiers live."""
    cases = [v for v in repo.list_cases() if person is None or person in {v.owner, v.backup_owner}]
    lanes = Counter(idx.lane_for(v, today) for v in cases)
    tiers = Counter(prio.compute(v, today).tier for v in cases)
    return cases, lanes, tiers


def _check_matches_brute(client, repo, headers, person=None):
    t = client.get("/api/today?per_lane=5", headers=headers).json()
    today = date.fromisoformat(t["today"])
    cases, lanes, tiers = _brute(repo, today, person)
    assert t["total"] == len(cases)
    assert {k: v["count"] for k, v in t["lanes"].items()} == {k: lanes.get(k, 0) for k in idx.LANES}
    assert t["tier_counts"] == {k: tiers.get(k, 0) for k in idx.TIERS}
    for lane, body in t["lanes"].items():
        assert len(body["cases"]) == min(5, lanes.get(lane, 0))
        # top of each lane is the highest priority, same order as sorting all cases of that lane live
        live = sorted(
            (v for v in cases if idx.lane_for(v, today) == lane),
            key=lambda v: idx.sort_key({**idx.index_fields(v, today), "id": v.id}),
        )
        assert [c["id"] for c in body["cases"]] == [v.id for v in live[:5]]
        assert all(
            c["priority"]["tier"] == idx.index_fields(repo.get_case(c["id"]), today)["idx_tier"] for c in body["cases"]
        )
    return t


def test_today_counts_and_order_match_reading_everything(setup):
    _, repo, client = setup
    _check_matches_brute(client, repo, SUP)
    _check_matches_brute(client, repo, WORKER, person="demo-worker-01")


def test_counts_stay_exact_as_days_pass(setup):
    """Due-soon and overdue change with time only; the recheck date makes sure stored tiers follow."""
    _, repo, client = setup
    for days in (1, 2, 3, 5):
        r = client.post("/api/demo/clock", json={"advance_days": days}, headers=SUP).json()
        assert r["ladder"]["conflicts"] == 0
        _check_matches_brute(client, repo, SUP)
        _check_matches_brute(client, repo, WORKER, person="demo-worker-01")


def test_ladder_reads_and_writes_only_due_cases(setup):
    _, repo, client = setup
    total = len(repo.list_cases())
    before = repo.write_ops
    r = client.post("/api/demo/clock", json={"advance_days": 1}, headers=SUP).json()["ladder"]
    assert 0 < r["cases_checked"] < total  # only cases with a step due are even read
    assert r["cases_touched"] <= r["cases_checked"]
    # one projection write per touched case plus its new events, plus stored-field refreshes
    assert repo.write_ops - before <= r["cases_touched"] + r["steps_run"] * 2 + r["reindexed"]
    again = client.post("/api/ladder/run", headers=SUP).json()
    assert again["steps_run"] == 0 and again["cases_touched"] == 0  # each step runs once


def test_bulk_ladder_equals_step_by_step(lib, coord):
    """Batched run_all produces the same events as running each case one by one."""
    a, b = MemoryRepository(), MemoryRepository()
    for r in (a, b):
        r.indexer = lambda v: idx.index_fields(v, NOW.date())
        for i in range(12):
            s = screening(screened_at=NOW.date().isoformat())
            pw = lib.match(s["screening_type"], s["result"], s["severity"])
            cmd.open_case(r, case_id=f"C-{i}", screening=s, pathway=pw, actor=coord, owner="w1", now=NOW)
    day = NOW.date() + timedelta(days=10)
    a.indexer = b.indexer = lambda v: idx.index_fields(v, day)
    res = ladder.run_all(a, today=day, now=NOW + timedelta(days=10))
    for i in range(12):
        ladder.run_case(b, f"C-{i}", today=day, now=NOW + timedelta(days=10))
    assert res["cases_touched"] == 12
    for i in range(12):
        ea = [(e.seq, e.type, e.payload) for e in a.load_events(f"C-{i}")]
        eb = [(e.seq, e.type, e.payload) for e in b.load_events(f"C-{i}")]
        assert ea == eb
        assert a.get_case(f"C-{i}").state == S.ESCALATED


def test_ladder_skips_paused_and_reports_conflicts(lib, coord):
    repo = MemoryRepository(indexer=lambda v: idx.index_fields(v, NOW.date()))
    s = screening()
    pw = lib.match(s["screening_type"], s["result"], s["severity"])
    cmd.open_case(repo, case_id="C-1", screening=s, pathway=pw, actor=coord, owner="w1", now=NOW)
    v = repo.get_case("C-1")
    # a stale pending write (someone appended meanwhile) is refused and reported, not applied
    ev = repo.load_events("C-1")
    assert repo.commit_many([("C-1", ev[-1].seq - 1, [ev[-1]], v)]) == ["C-1"]
    assert repo.commit_many([("C-1", 0, [], v)]) == []  # nothing to write is a no-op, never a blind overwrite
    assert idx.ladder_due(v) is not None
    cmd.report_red_flag(repo, "C-1", actor=coord, source="staff", code="chest_pain", now=NOW)
    paused = repo.get_case("C-1")
    assert paused.automation_paused and idx.ladder_due(paused) is None
    assert repo.ladder_due("9999-01-01") == []  # a paused case is never picked up by the ladder


def test_demo_clock_survives_restart(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="5000", RATE_LIMIT_SENSITIVE_PER_MINUTE="500"
    )
    repo = MemoryRepository()
    c1 = TestClient(create_app(cfg, repo))
    c1.post("/api/demo/clock", json={"advance_days": 4}, headers=SUP)
    c2 = TestClient(create_app(cfg, repo))
    assert c2.get("/api/clock", headers=SUP).json()["offset_days"] == 4


def test_cases_endpoint_is_limited_and_scoped(setup):
    _, repo, client = setup
    r = client.get("/api/cases?lane=overdue&limit=3", headers=SUP).json()
    assert len(r["cases"]) <= 3 and r["total"] == sum(
        1 for v in repo.list_cases() if idx.lane_for(v, date.fromisoformat(r["today"])) == "overdue"
    )
    assert client.get("/api/cases?lane=nope", headers=SUP).status_code == 400
    assert client.get("/api/cases?limit=1000", headers=SUP).status_code == 422
    w = client.get("/api/cases?limit=200", headers=WORKER).json()
    assert w["cases"] and all("demo-worker-01" in {c["owner"], c.get("backup_owner")} for c in w["cases"])


def test_recheck_dates():
    from loopcloser.domain.case import CaseView

    base = dict(
        id="C",
        participant_id="P",
        screening_id="S",
        screening_type="bp",
        severity="abnormal",
        pathway_id="p",
        pathway_version="1",
        pathway_signoff_status="pending",
    )
    v = CaseView(**base, due_date=date(2026, 10, 20))
    assert idx.recheck_on(v, date(2026, 10, 10)) == date(2026, 10, 17)  # due soon starts
    assert idx.recheck_on(v, date(2026, 10, 17)) == date(2026, 10, 21)  # overdue starts
    assert idx.recheck_on(v, date(2026, 10, 21)) is None
    assert idx.recheck_on(CaseView(**base), date(2026, 10, 10)) is None


def test_clock_reset_by_operator_is_picked_up_and_reindexes(make_cfg):
    cfg = make_cfg(
        APP_ENV="test", DEMO_MODE="true", RATE_LIMIT_PER_MINUTE="5000", RATE_LIMIT_SENSITIVE_PER_MINUTE="500"
    )
    repo = MemoryRepository()
    c = TestClient(create_app(cfg, repo))
    c.post("/api/demo/seed", json={"n": 100}, headers=SUP)
    c.post("/api/demo/clock", json={"advance_days": 20}, headers=SUP)
    repo.set_meta("clock", {"offset_days": 0})  # what scripts/reset_demo.py does
    c2 = TestClient(create_app(cfg, repo))  # a restarted instance
    assert c2.get("/api/clock", headers=SUP).json()["offset_days"] == 0
    _check_matches_brute(c2, repo, SUP)
