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
