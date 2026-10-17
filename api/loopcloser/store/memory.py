"""In-memory repository for local runs and tests."""

from __future__ import annotations

import threading

from ..domain.case import CaseView
from ..domain.errors import Conflict
from ..domain.events import Event


class MemoryRepository:
    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._cases: dict[str, CaseView] = {}
        self._lock = threading.Lock()

    def load_events(self, case_id: str) -> list[Event]:
        with self._lock:
            return list(self._events.get(case_id, []))

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

    def get_case(self, case_id: str) -> CaseView | None:
        with self._lock:
            c = self._cases.get(case_id)
            return c.model_copy(deep=True) if c else None

    def list_cases(self) -> list[CaseView]:
        with self._lock:
            return [c.model_copy(deep=True) for c in self._cases.values()]

    def ping(self) -> bool:
        return True
