"""Storage interface. Events are append-only: there is no update or delete."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from ..domain.case import CaseView
from ..domain.events import Event

# Computes the stored idx_* query fields for a projection (domain/indexing.py). Set by the app.
Indexer = Callable[[CaseView], dict[str, Any]]

# One pending append: (case_id, expected_version, new_events, projection)
Pending = tuple[str, int, list[Event], CaseView]


class CaseRepository(Protocol):
    indexer: Indexer | None

    def load_events(self, case_id: str) -> list[Event]: ...

    def load_events_many(self, case_ids: list[str]) -> dict[str, list[Event]]: ...

    def append(self, case_id: str, events: list[Event], expected_version: int, projection: CaseView) -> None:
        """Atomically append events and write the projection.

        Raises Conflict if the case's current version is not expected_version
        (optimistic concurrency) or if any event id already exists.
        """
        ...

    def commit_many(self, items: list[Pending]) -> list[str]:
        """Append to many cases in bulk with the same guarantees as append. Returns ids that conflicted
        (left untouched, so a later run picks them up)."""
        ...

    def get_case(self, case_id: str) -> CaseView | None: ...

    def list_cases(self) -> list[CaseView]: ...

    def existing_ids(self) -> set[str]: ...

    def create_cases(self, cases: list[tuple[str, list[Event], CaseView]]) -> list[str]:
        """Write brand-new cases (full event log plus projection) in bulk.

        A case that already exists is never touched; its id is returned in the skipped list.
        """
        ...

    # Query by the stored idx_* fields. person = owner or backup owner; patient = patient_uid.
    def query(
        self,
        *,
        lane: str | None = None,
        person: str | None = None,
        patient: str | None = None,
        screening_type: str | None = None,
        limit: int = 50,
    ) -> list[CaseView]: ...

    def count(
        self,
        *,
        lane: str | None = None,
        tier: str | None = None,
        person: str | None = None,
        patient: str | None = None,
        screening_type: str | None = None,
        status: str | None = None,
        lost: bool | None = None,
    ) -> int: ...

    def search_ids(self, prefix: str, limit: int = 20) -> list[str]:
        """Case ids starting with prefix (case-sensitive in Firestore; ids are upper case)."""
        ...

    # SIMULATED contact details (fictional name and phone) kept apart from the case projection, which
    # staff clients can read. Server-only; every reveal is logged as an event on the case.
    def put_contacts(self, contacts: dict[str, dict[str, str]]) -> None: ...

    def get_contact(self, participant_id: str) -> dict[str, str] | None: ...

    def ladder_due(self, today_iso: str) -> list[CaseView]: ...

    def reindex(self, today_iso: str, *, everything: bool = False) -> int:
        """Recompute idx_* fields for cases whose idx_recheck is due (or all). Returns how many changed."""
        ...

    def get_meta(self, key: str) -> dict[str, Any]: ...

    def set_meta(self, key: str, value: dict[str, Any]) -> None: ...

    def ping(self) -> bool: ...
