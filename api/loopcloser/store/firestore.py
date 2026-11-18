"""Firestore repository.

Layout (the (default) database of LoopCloser's own project, which gets the free tier):
  cases/{caseId}                 projection (rebuildable cache, read by the web app) plus idx_* query fields
  cases/{caseId}/events/{seq}    append-only event log, the source of truth
  meta/{key}                     small server-only settings, e.g. the demo clock
  contacts/{participantId}       SIMULATED fictional name and phone, server-only (rules deny clients)

Appends use create(), which fails if the document exists, so an event can never be overwritten.
Single appends run in a transaction that also checks the case version. Bulk appends (seeding, the
escalation ladder) use batched writes: each batch is atomic and its event create() calls fail the
whole batch if anyone appended to one of its cases meanwhile; those cases then fall back to one
transaction each, and real conflicts are reported and left for the next run.
Firestore security rules deny all client writes (see firestore.rules).
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..domain.case import CaseView
from ..domain.errors import Conflict
from ..domain.events import Event
from .base import Indexer, Pending

_client = None
_BATCH_OPS = 450  # Firestore allows 500 writes per batch; keep headroom
_IDX_ORDER = (("idx_rank", "ASCENDING"), ("idx_score", "DESCENDING"), ("idx_due", "ASCENDING"))


def _db():
    global _client
    if _client is None:
        from google.cloud import firestore

        _client = firestore.Client(
            project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        )
    return _client


class FirestoreRepository:
    def __init__(self, client=None, indexer: Indexer | None = None) -> None:
        self.db = client or _db()
        self.cases = self.db.collection("cases")
        self.meta = self.db.collection("meta")
        self.contacts = self.db.collection("contacts")
        self.indexer = indexer

    def _doc(self, projection: CaseView) -> dict[str, Any]:
        d = projection.to_doc()
        if self.indexer:
            d.update(self.indexer(projection))
        return d

    def _events_col(self, case_id: str):
        return self.cases.document(case_id).collection("events")

    def load_events(self, case_id: str) -> list[Event]:
        docs = self._events_col(case_id).order_by("seq").stream()
        return [Event.from_doc(d.to_dict()) for d in docs]

    def load_events_many(self, case_ids: list[str]) -> dict[str, list[Event]]:
        if not case_ids:
            return {}
        with ThreadPoolExecutor(max_workers=16) as pool:
            return dict(zip(case_ids, pool.map(self.load_events, case_ids), strict=True))

    def append(self, case_id: str, events: list[Event], expected_version: int, projection: CaseView) -> None:
        from google.api_core.exceptions import AlreadyExists
        from google.api_core.exceptions import Conflict as GConflict
        from google.cloud import firestore

        case_ref = self.cases.document(case_id)

        @firestore.transactional
        def _txn(txn):
            snap = case_ref.get(transaction=txn)
            current = (snap.to_dict() or {}).get("version", 0) if snap.exists else 0
            if current != expected_version:
                raise Conflict(f"case {case_id} changed (version {current}, expected {expected_version})")
            for ev in events:
                txn.create(self._events_col(case_id).document(f"{ev.seq:06d}"), ev.to_doc())
            txn.set(case_ref, self._doc(projection))

        try:
            _txn(self.db.transaction())
        except (AlreadyExists, GConflict) as exc:
            raise Conflict(f"event already exists for case {case_id}") from exc

    def _batched(self, items: list, n_ops, write, fallback) -> list[str]:
        """Group items into batches under the op limit; on a failed batch, retry its items one by one."""
        from google.api_core.exceptions import AlreadyExists, FailedPrecondition, NotFound
        from google.api_core.exceptions import Conflict as GConflict

        failed: list[str] = []
        chunk: list = []
        ops = 0

        def flush():
            nonlocal chunk, ops
            if not chunk:
                return
            batch = self.db.batch()
            for it in chunk:
                write(batch, it)
            try:
                batch.commit()
            except (AlreadyExists, GConflict, FailedPrecondition, NotFound):
                for it in chunk:
                    if not fallback(it):
                        failed.append(it[0])
            chunk, ops = [], 0

        for it in items:
            k = n_ops(it)
            if ops + k > _BATCH_OPS:
                flush()
            chunk.append(it)
            ops += k
        flush()
        return failed

    def commit_many(self, items: list[Pending]) -> list[str]:
        items = [it for it in items if it[2]]  # an item with no new events would be a blind overwrite

        def write(batch, it):
            case_id, _expected, events, projection = it
            for ev in events:
                batch.create(self._events_col(case_id).document(f"{ev.seq:06d}"), ev.to_doc())
            batch.set(self.cases.document(case_id), self._doc(projection))

        def fallback(it) -> bool:
            case_id, expected, events, projection = it
            try:
                self.append(case_id, events, expected, projection)
                return True
            except Conflict:
                return False

        return self._batched(items, lambda it: len(it[2]) + 1, write, fallback)

    def create_cases(self, cases: list[tuple[str, list[Event], CaseView]]) -> list[str]:
        """Batched create() writes. create() fails if a document exists, so nothing is overwritten."""

        def write(batch, it):
            case_id, events, projection = it
            batch.create(self.cases.document(case_id), self._doc(projection))
            for ev in events:
                batch.create(self._events_col(case_id).document(f"{ev.seq:06d}"), ev.to_doc())

        def fallback(it) -> bool:
            case_id, events, projection = it
            try:
                self.append(case_id, events, 0, projection)
                return True
            except Conflict:
                return False

        return self._batched(cases, lambda it: len(it[1]) + 1, write, fallback)

    def get_case(self, case_id: str) -> CaseView | None:
        snap = self.cases.document(case_id).get()
        return CaseView.model_validate(snap.to_dict()) if snap.exists else None

    def list_cases(self) -> list[CaseView]:
        return [CaseView.model_validate(d.to_dict()) for d in self.cases.stream()]

    def existing_ids(self) -> set[str]:
        return {d.id for d in self.cases.select([]).stream()}

    # ------------------------------------------------------------ queries on idx_* fields

    def _filtered(self, lane=None, tier=None, person=None, patient=None, screening_type=None, status=None, lost=None):
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self.cases
        if screening_type is not None:
            q = q.where(filter=FieldFilter("screening_type", "==", screening_type))
        if status is not None:
            q = q.where(filter=FieldFilter("idx_status", "==", status))
        if lost is not None:
            q = q.where(filter=FieldFilter("idx_lost", "==", lost))
        if patient is not None:
            q = q.where(filter=FieldFilter("patient_uid", "==", patient))
        if person is not None:
            q = q.where(filter=FieldFilter("idx_people", "array_contains", person))
        if lane is not None:
            q = q.where(filter=FieldFilter("idx_lane", "==", lane))
        if tier is not None:
            q = q.where(filter=FieldFilter("idx_tier", "==", tier))
        return q

    def query(self, *, lane=None, person=None, patient=None, screening_type=None, limit: int = 50) -> list[CaseView]:
        q = self._filtered(lane=lane, person=person, patient=patient, screening_type=screening_type)
        if patient is None:  # a patient has one or two cases; no ordering index needed
            for field, direction in _IDX_ORDER:
                q = q.order_by(field, direction=direction)
            q = q.order_by("__name__")
        return [CaseView.model_validate(d.to_dict()) for d in q.limit(limit).stream()]

    def count(
        self, *, lane=None, tier=None, person=None, patient=None, screening_type=None, status=None, lost=None
    ) -> int:
        """Aggregation count: billed as one read per 1,000 matching index entries, not per document."""
        q = self._filtered(
            lane=lane,
            tier=tier,
            person=person,
            patient=patient,
            screening_type=screening_type,
            status=status,
            lost=lost,
        )
        res = q.count().get()
        return int(res[0][0].value)

    def slot_counts(self, clinic: str) -> dict[str, int]:
        """One equality filter (single-field index, no composite index). Reads one document per booked case."""
        from google.cloud.firestore_v1.base_query import FieldFilter

        out: dict[str, int] = {}
        q = self.cases.where(filter=FieldFilter("idx_slot_clinic", "==", clinic)).select(["idx_slot"])
        for d in q.stream():
            sid = (d.to_dict() or {}).get("idx_slot")
            if sid:
                out[sid] = out.get(sid, 0) + 1
        return out

    def search_ids(self, prefix: str, limit: int = 20) -> list[str]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        start = self.cases.document(prefix)
        end = self.cases.document(prefix + "\uf8ff")
        q = (
            self.cases.where(filter=FieldFilter("__name__", ">=", start))
            .where(filter=FieldFilter("__name__", "<=", end))
            .select([])
            .limit(limit)
        )
        return [d.id for d in q.stream()]

    def put_contacts(self, contacts: dict[str, dict[str, str]]) -> None:
        items = list(contacts.items())
        for i in range(0, len(items), _BATCH_OPS):
            batch = self.db.batch()
            for pid, c in items[i : i + _BATCH_OPS]:
                batch.set(self.contacts.document(pid), dict(c))
            batch.commit()

    def get_contact(self, participant_id: str) -> dict[str, str] | None:
        snap = self.contacts.document(participant_id).get()
        return snap.to_dict() if snap.exists else None

    def ladder_due(self, today_iso: str) -> list[CaseView]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self.cases.where(filter=FieldFilter("idx_ladder_due", "<=", today_iso))
        return [CaseView.model_validate(d.to_dict()) for d in q.stream()]

    def reindex(self, today_iso: str, *, everything: bool = False) -> int:
        from google.cloud.firestore_v1.base_query import FieldFilter

        if not self.indexer:
            return 0
        q = self.cases if everything else self.cases.where(filter=FieldFilter("idx_recheck", "<=", today_iso))
        items = []
        for snap in q.stream():
            d = snap.to_dict()
            new = self.indexer(CaseView.model_validate(d))
            if any(d.get(k) != v for k, v in new.items()):
                items.append((snap.id, snap.update_time, new))

        def write(batch, it):
            # Precondition: only if the case was not rewritten since we read it (a newer write
            # already carries fresh idx_* fields).
            batch.update(self.cases.document(it[0]), it[2], option=self.db.write_option(last_update_time=it[1]))

        def fallback(it) -> bool:
            from google.api_core.exceptions import FailedPrecondition

            try:
                self.cases.document(it[0]).update(it[2], option=self.db.write_option(last_update_time=it[1]))
                return True
            except FailedPrecondition:
                return True  # changed meanwhile; that write already indexed it

        self._batched(items, lambda it: 1, write, fallback)
        return len(items)

    def get_meta(self, key: str) -> dict[str, Any]:
        snap = self.meta.document(key).get()
        return snap.to_dict() or {} if snap.exists else {}

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        self.meta.document(key).set(value)

    def ping(self) -> bool:
        list(self.cases.limit(1).stream())
        return True
