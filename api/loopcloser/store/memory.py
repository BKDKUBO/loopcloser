"""In-memory repository for local runs and tests. Mirrors the Firestore repository, including the
idx_* query fields, so the same queries are tested without the emulator."""

from __future__ import annotations

import threading
from typing import Any

from ..domain.case import CaseView
from ..domain.errors import Conflict
from ..domain.events import Event
from ..domain.indexing import FAR, sort_key
from .base import Indexer, Pending


class MemoryRepository:
    def __init__(self, indexer: Indexer | None = None) -> None:
        self._events: dict[str, list[Event]] = {}
        self._cases: dict[str, CaseView] = {}
        self._idx: dict[str, dict[str, Any]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._contacts: dict[str, dict[str, str]] = {}  # SIMULATED names and phones, server-only
        self._lock = threading.Lock()
        self.indexer = indexer
        self.write_ops = 0  # for tests: documents written

    def _index(self, case_id: str, projection: CaseView) -> None:
        if self.indexer:
            self._idx[case_id] = self.indexer(projection)

    def load_events(self, case_id: str) -> list[Event]:
        with self._lock:
            return list(self._events.get(case_id, []))

    def load_events_many(self, case_ids: list[str]) -> dict[str, list[Event]]:
        return {c: self.load_events(c) for c in case_ids}

    def append(self, case_id: str, events: list[Event], expected_version: int, projection: CaseView) -> None:
        with self._lock:
            log = self._events.setdefault(case_id, [])
            current = log[-1].seq if log else 0
            if current != expected_version:
                raise Conflict(f"case {case_id} changed (version {current}, expected {expected_version})")
            ids = {e.id for e in log}
            for i, ev in enumerate(events, start=1):
                if ev.id in ids or ev.seq != current + i:
                    raise Conflict(f"event {ev.id} out of order or already exists")
            log.extend(events)
            self._cases[case_id] = projection
            self._index(case_id, projection)
            self.write_ops += len(events) + 1

    def commit_many(self, items: list[Pending]) -> list[str]:
        items = [it for it in items if it[2]]  # an item with no new events would be a blind overwrite
        conflicts = []
        for case_id, expected, events, projection in items:
            try:
                self.append(case_id, events, expected, projection)
            except Conflict:
                conflicts.append(case_id)
        return conflicts

    def get_case(self, case_id: str) -> CaseView | None:
        with self._lock:
            c = self._cases.get(case_id)
            return c.model_copy(deep=True) if c else None

    def list_cases(self) -> list[CaseView]:
        with self._lock:
            return [c.model_copy(deep=True) for c in self._cases.values()]

    def existing_ids(self) -> set[str]:
        with self._lock:
            return set(self._cases)

    def create_cases(self, cases: list[tuple[str, list[Event], CaseView]]) -> list[str]:
        skipped = []
        for case_id, events, projection in cases:
            try:
                self.append(case_id, events, 0, projection)
            except Conflict:
                skipped.append(case_id)
        return skipped

    def _match(self, case_id: str, lane, tier, person, patient, screening_type=None, status=None, lost=None) -> bool:
        ix = self._idx.get(case_id)
        if ix is None:
            return False
        v = self._cases[case_id]
        return (
            (lane is None or ix["idx_lane"] == lane)
            and (tier is None or ix["idx_tier"] == tier)
            and (person is None or person in ix["idx_people"])
            and (patient is None or v.patient_uid == patient)
            and (screening_type is None or v.screening_type == screening_type)
            and (status is None or ix.get("idx_status") == status)
            and (lost is None or ix.get("idx_lost") == lost)
        )

    def query(self, *, lane=None, person=None, patient=None, screening_type=None, limit: int = 50) -> list[CaseView]:
        with self._lock:
            ids = [c for c in self._cases if self._match(c, lane, None, person, patient, screening_type)]
            ids.sort(key=lambda c: sort_key({**self._idx[c], "id": c}))
            return [self._cases[c].model_copy(deep=True) for c in ids[:limit]]

    def count(
        self, *, lane=None, tier=None, person=None, patient=None, screening_type=None, status=None, lost=None
    ) -> int:
        with self._lock:
            return sum(
                1 for c in self._cases if self._match(c, lane, tier, person, patient, screening_type, status, lost)
            )

    def search_ids(self, prefix: str, limit: int = 20) -> list[str]:
        with self._lock:
            return sorted(c for c in self._cases if c.upper().startswith(prefix.upper()))[:limit]

    def put_contacts(self, contacts: dict[str, dict[str, str]]) -> None:
        with self._lock:
            self._contacts.update({k: dict(v) for k, v in contacts.items()})

    def get_contact(self, participant_id: str) -> dict[str, str] | None:
        with self._lock:
            c = self._contacts.get(participant_id)
            return dict(c) if c else None

    def ladder_due(self, today_iso: str) -> list[CaseView]:
        with self._lock:
            return [
                self._cases[c].model_copy(deep=True)
                for c, ix in sorted(self._idx.items())
                if ix["idx_ladder_due"] <= today_iso
            ]

    def reindex(self, today_iso: str, *, everything: bool = False) -> int:
        if not self.indexer:
            return 0
        changed = 0
        with self._lock:
            for c, v in self._cases.items():
                ix = self._idx.get(c)
                if everything or ix is None or ix.get("idx_recheck", FAR) <= today_iso:
                    new = self.indexer(v)
                    if new != ix:
                        self._idx[c] = new
                        changed += 1
                        self.write_ops += 1
        return changed

    def index_of(self, case_id: str) -> dict[str, Any] | None:
        return self._idx.get(case_id)

    def get_meta(self, key: str) -> dict[str, Any]:
        return dict(self._meta.get(key, {}))

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        self._meta[key] = dict(value)

    def ping(self) -> bool:
        return True
