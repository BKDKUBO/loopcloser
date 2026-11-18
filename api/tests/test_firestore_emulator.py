"""Runs against the Firestore emulator only (skipped otherwise):
firebase emulators:exec --only firestore --project demo-loopcloser "cd api && .venv/bin/pytest -m emulator"
"""

import os

import pytest

from loopcloser.domain import commands as cmd
from loopcloser.domain.errors import Conflict
from loopcloser.domain.states import CaseState as S

from .conftest import NOW, screening

pytestmark = [
    pytest.mark.emulator,
    pytest.mark.skipif(not os.getenv("FIRESTORE_EMULATOR_HOST"), reason="needs the Firestore emulator"),
]


@pytest.fixture
def fs_repo():
    from google.cloud import firestore

    from loopcloser.store.firestore import FirestoreRepository

    client = firestore.Client(project="demo-loopcloser", database="(default)")
    for d in client.collection("cases").stream():
        for e in d.reference.collection("events").stream():
            e.reference.delete()
        d.reference.delete()
    return FirestoreRepository(client)


def test_firestore_roundtrip_and_append_only(fs_repo, lib, coord):
    pw = lib.match("fit", "positive", "abnormal")
    cmd.open_case(fs_repo, case_id="C-1", screening=screening(), pathway=pw, actor=coord, owner="worker-01", now=NOW)
    cmd.transition(fs_repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    v = fs_repo.get_case("C-1")
    assert v.state == S.REVIEWED and v.version == 2
    assert [e.seq for e in fs_repo.load_events("C-1")] == [1, 2]
    assert v.to_doc() == cmd.rebuild(fs_repo, "C-1").to_doc()
    with pytest.raises(Conflict):
        fs_repo.append("C-1", fs_repo.load_events("C-1")[:1], 0, v)


def test_firestore_bulk_create_never_overwrites(fs_repo, lib, coord):
    from loopcloser.store.memory import MemoryRepository

    pw = lib.match("fit", "positive", "abnormal")
    stage = MemoryRepository()
    for i in range(120):  # more than one batch
        cmd.open_case(stage, case_id=f"C-{i}", screening=screening(), pathway=pw, actor=coord, now=NOW)
    cmd.open_case(fs_repo, case_id="C-5", screening=screening(), pathway=pw, actor=coord, owner="kept", now=NOW)
    items = [(c, stage.load_events(c), stage.get_case(c)) for c in sorted(stage.existing_ids())]
    skipped = fs_repo.create_cases(items)
    assert skipped == ["C-5"]
    assert len(fs_repo.existing_ids()) == 120
    assert fs_repo.get_case("C-5").owner == "kept"
    assert [e.seq for e in fs_repo.load_events("C-7")] == [e.seq for e in stage.load_events("C-7")]


def test_firestore_queries_counts_ladder_and_reindex(fs_repo, lib, coord):
    from datetime import timedelta

    from loopcloser.domain import indexing as idx
    from loopcloser.domain import ladder
    from loopcloser.store.memory import MemoryRepository

    day = {"d": NOW.date()}
    mem = MemoryRepository()
    for r in (fs_repo, mem):
        r.indexer = lambda v: idx.index_fields(v, day["d"])
    pw = lib.match("fit", "positive", "abnormal")
    for i in range(30):
        s = screening(screened_at=(NOW.date() - timedelta(days=i % 15)).isoformat())
        for r in (fs_repo, mem):
            cmd.open_case(r, case_id=f"C-{i:02d}", screening=s, pathway=pw, actor=coord, owner=f"w{i % 3}", now=NOW)

    def same():
        for lane in idx.LANES:
            assert fs_repo.count(lane=lane) == mem.count(lane=lane)
            assert [v.id for v in fs_repo.query(lane=lane, limit=7)] == [v.id for v in mem.query(lane=lane, limit=7)]
            assert fs_repo.count(lane=lane, person="w1") == mem.count(lane=lane, person="w1")
        for t in idx.TIERS:
            assert fs_repo.count(tier=t) == mem.count(tier=t)

    same()
    day["d"] = NOW.date() + timedelta(days=25)
    assert fs_repo.reindex(day["d"].isoformat()) == mem.reindex(day["d"].isoformat()) > 0
    same()
    due = fs_repo.ladder_due(day["d"].isoformat())
    assert sorted(v.id for v in due) == sorted(v.id for v in mem.ladder_due(day["d"].isoformat())) and due
    res = ladder.run_all(fs_repo, today=day["d"], now=NOW + timedelta(days=25))
    assert res["conflicts"] == 0 and res["cases_touched"] == len(due)
    assert ladder.run_all(fs_repo, today=day["d"], now=NOW + timedelta(days=25))["steps_run"] == 0
    # a stale bulk write is refused and reported, never applied over newer events
    v = fs_repo.get_case("C-00")
    n = len(fs_repo.load_events("C-00"))
    last = fs_repo.load_events("C-00")[-1]
    assert fs_repo.commit_many([("C-00", last.seq - 1, [last], v)]) == ["C-00"]
    assert len(fs_repo.load_events("C-00")) == n


def test_firestore_slot_counts(fs_repo, lib, coord):
    from datetime import date

    from loopcloser.domain import indexing as idx

    fs_repo.indexer = lambda v: idx.index_fields(v, date(2026, 10, 17))
    pw = lib.match("fit", "positive", "abnormal")
    sid = "SITE-A|2026-10-19T09:00"
    for cid in ("C-1", "C-2"):
        cmd.open_case(fs_repo, case_id=cid, screening=screening(), pathway=pw, actor=coord, owner="w", now=NOW)
        for t, p in [
            (S.REVIEWED, {}),
            (S.PATIENT_NOTIFIED, {}),
            (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        ]:
            cmd.transition(fs_repo, cid, t, actor=coord, payload=p, now=NOW)
        cmd.book_appointment(
            fs_repo,
            cid,
            slot_id=sid,
            actor=coord,
            today=date(2026, 10, 17),
            booked_in_slot=fs_repo.slot_counts("SITE-A").get(sid, 0),
            masked_participant="P-••••42",
            now=NOW,
        )
    assert fs_repo.slot_counts("SITE-A") == {sid: 2}
    assert fs_repo.slot_counts("SITE-B") == {}
