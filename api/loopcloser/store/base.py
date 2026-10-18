"""Storage interface. Events are append-only: there is no update or delete."""

from __future__ import annotations

from typing import Protocol

from ..domain.case import CaseView
from ..domain.events import Event


class CaseRepository(Protocol):
    def load_events(self, case_id: str) -> list[Event]: ...

    def append(self, case_id: str, events: list[Event], expected_version: int, projection: CaseView) -> None:
        """Atomically append events and write the projection.

        Raises Conflict if the case's current version is not expected_version
        (optimistic concurrency) or if any event id already exists.
        """
        ...

    def get_case(self, case_id: str) -> CaseView | None: ...

    def list_cases(self) -> list[CaseView]: ...

    def existing_ids(self) -> set[str]: ...

    def create_cases(self, cases: list[tuple[str, list[Event], CaseView]]) -> list[str]:
        """Write brand-new cases (full event log plus projection) in bulk.

        A case that already exists is never touched; its id is returned in the skipped list.
        """
        ...

    def ping(self) -> bool: ...
