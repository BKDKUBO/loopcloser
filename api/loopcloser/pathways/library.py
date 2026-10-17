"""Versioned pathway library (PLAN_FINAL.md section 5).

Each pathway is a JSON config at data/<id>@<version>.json. A published version is
immutable: LOCK.json stores a SHA-256 per id@version and the test suite fails if a
published file changes. To change a pathway, add a new version file.

Every pathway is marked "pending clinical sign-off". The team has no clinician, so
deadlines are "configurable default, pending clinical review".
"""

from __future__ import annotations

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).parent / "data"
LOCK_PATH = Path(__file__).parent / "LOCK.json"
PENDING = "pending_clinical_signoff"


class Trigger(BaseModel):
    screening_types: list[str]
    results: list[str]
    severities: list[str]

    def matches(self, screening_type: str, result: str, severity: str) -> bool:
        def ok(allowed: list[str], value: str) -> bool:
            return "*" in allowed or value in allowed

        return ok(self.screening_types, screening_type) and ok(self.results, result) and ok(self.severities, severity)

    @property
    def specificity(self) -> int:
        # Screening type matters most, then result, then severity.
        weights = ((self.screening_types, 4), (self.results, 2), (self.severities, 1))
        return sum(w for f, w in weights if "*" not in f)


class Pathway(BaseModel):
    id: str
    version: str
    name: str
    scope: Literal["MUST", "SHOULD", "COULD"]
    trigger: Trigger
    next_action: str
    default_deadline_days: int = Field(ge=0)
    deadline_label: str
    red_flag_route: bool = False
    parameters: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(min_length=1)
    signoff_status: Literal["pending_clinical_signoff", "signed_off"]
    notes: str = ""

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PathwayLibrary:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self._by_key: dict[str, Pathway] = {}
        for f in sorted(data_dir.glob("*@*.json")):
            p = Pathway.model_validate(json.loads(f.read_text("utf-8")))
            if f.stem != p.key:
                raise ValueError(f"{f.name}: file name must be {p.key}.json")
            if p.key in self._by_key:
                raise ValueError(f"duplicate pathway {p.key}")
            self._by_key[p.key] = p

    def all(self) -> list[Pathway]:
        return list(self._by_key.values())

    def latest(self) -> list[Pathway]:
        best: dict[str, Pathway] = {}
        for p in self._by_key.values():
            if p.id not in best or _version_tuple(p.version) > _version_tuple(best[p.id].version):
                best[p.id] = p
        return sorted(best.values(), key=lambda p: p.id)

    def get(self, pathway_id: str, version: str | None = None) -> Pathway | None:
        if version:
            return self._by_key.get(f"{pathway_id}@{version}")
        return next((p for p in self.latest() if p.id == pathway_id), None)

    def match(self, screening_type: str, result: str, severity: str) -> Pathway | None:
        """Pick the most specific latest pathway whose trigger matches. Deterministic, no AI."""
        hits = [p for p in self.latest() if p.trigger.matches(screening_type, result, severity)]
        if not hits:
            return None
        hits.sort(key=lambda p: (-p.trigger.specificity, p.id))
        return hits[0]

    def lock_mismatches(self, lock_path: Path = LOCK_PATH) -> list[str]:
        lock = json.loads(lock_path.read_text("utf-8")) if lock_path.exists() else {}
        problems = []
        for key in self._by_key:
            h = file_hash(self.data_dir / f"{key}.json")
            if key not in lock:
                problems.append(f"{key}: not in LOCK.json (run: python -m loopcloser.pathways.library --lock-new)")
            elif lock[key] != h:
                problems.append(f"{key}: published version changed. Add a new version instead.")
        return problems


@lru_cache(maxsize=1)
def default_library() -> PathwayLibrary:
    return PathwayLibrary()


def _lock_new() -> int:
    lib = PathwayLibrary()
    lock = json.loads(LOCK_PATH.read_text("utf-8")) if LOCK_PATH.exists() else {}
    for p in lib.all():
        h = file_hash(DATA_DIR / f"{p.key}.json")
        if p.key in lock and lock[p.key] != h:
            print(f"refusing: {p.key} already published with a different hash", file=sys.stderr)
            return 1
        lock.setdefault(p.key, h)
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"locked {len(lock)} pathway versions")
    return 0


if __name__ == "__main__":
    if "--lock-new" in sys.argv:
        raise SystemExit(_lock_new())
    for p in PathwayLibrary().latest():
        print(p.key, p.scope, p.signoff_status)
