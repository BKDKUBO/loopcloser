"""Firestore repository.

Layout (the (default) database of LoopCloser's own project, which gets the free tier):
  cases/{caseId}                 projection (rebuildable cache, read by the web app)
  cases/{caseId}/events/{seq}    append-only event log, the source of truth

Appends run in a transaction and use create(), which fails if the document exists,
so an event can never be overwritten. Firestore security rules also deny all client
writes to events (see firestore.rules).
"""

from __future__ import annotations

import os

from ..domain.case import CaseView
from ..domain.errors import Conflict
from ..domain.events import Event

_client = None


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
    def __init__(self, client=None) -> None:
        self.db = client or _db()
        self.cases = self.db.collection("cases")

    def _events_col(self, case_id: str):
        return self.cases.document(case_id).collection("events")

    def load_events(self, case_id: str) -> list[Event]:
        docs = self._events_col(case_id).order_by("seq").stream()
        return [Event.from_doc(d.to_dict()) for d in docs]

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
            txn.set(case_ref, projection.to_doc())

        try:
            _txn(self.db.transaction())
        except (AlreadyExists, GConflict) as exc:
            raise Conflict(f"event already exists for case {case_id}") from exc

    def get_case(self, case_id: str) -> CaseView | None:
        snap = self.cases.document(case_id).get()
        return CaseView.model_validate(snap.to_dict()) if snap.exists else None

    def list_cases(self) -> list[CaseView]:
        return [CaseView.model_validate(d.to_dict()) for d in self.cases.stream()]

    def existing_ids(self) -> set[str]:
        return {d.id for d in self.cases.select([]).stream()}

    def create_cases(self, cases: list[tuple[str, list[Event], CaseView]]) -> list[str]:
        """Batched create() writes (max 500 per batch). create() fails if a document exists, so nothing is
        overwritten. If a batch hits an existing case, its cases fall back to one transaction each."""
        from google.api_core.exceptions import AlreadyExists
        from google.api_core.exceptions import Conflict as GConflict

        skipped: list[str] = []
        chunk: list[tuple[str, list[Event], CaseView]] = []
        ops = 0

        def flush():
            nonlocal chunk, ops
            if not chunk:
                return
            batch = self.db.batch()
            for case_id, events, projection in chunk:
                batch.create(self.cases.document(case_id), projection.to_doc())
                for ev in events:
                    batch.create(self._events_col(case_id).document(f"{ev.seq:06d}"), ev.to_doc())
            try:
                batch.commit()
            except (AlreadyExists, GConflict):
                for case_id, events, projection in chunk:
                    try:
                        self.append(case_id, events, 0, projection)
                    except Conflict:
                        skipped.append(case_id)
            chunk, ops = [], 0

        for item in cases:
            n = len(item[1]) + 1
            if ops + n > 450:
                flush()
            chunk.append(item)
            ops += n
        flush()
        return skipped

    def ping(self) -> bool:
        list(self.cases.limit(1).stream())
        return True
