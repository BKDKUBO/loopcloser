"""Approved patient message templates, English and Filipino (PLAN_FINAL.md section 2 and 11).

Official patient messages come ONLY from these templates. Staff pick a template; the
system fills in fixed placeholders. There is no free text and no AI text in official
messages. Gemini never sends anything.

Every template is marked "pending review" (clinical and native-speaker review) until
signed off. Published versions are immutable (LOCK.json), like pathways.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

DATA_DIR = Path(__file__).parent / "data"
LOCK_PATH = Path(__file__).parent / "LOCK.json"
LANGUAGES = ("en", "fil")
_FIELD = re.compile(r"\{(\w+)\}")


class TemplateError(ValueError):
    pass


class Template(BaseModel):
    id: str
    version: str
    name: str
    kind: Literal["official"]
    status: Literal["pending_review", "approved"]
    review_note: str
    channels: list[str]
    part_order: list[str]
    placeholders: list[str]
    lookups: dict[str, dict[str, dict[str, str]]]
    languages: dict[str, dict[str, str]]

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"

    def render(self, language: str, context: dict[str, Any]) -> dict[str, Any]:
        if language not in self.languages:
            raise TemplateError(f"{self.key} has no {language} version")
        missing = [p for p in self.placeholders if context.get(p) in (None, "")]
        if missing:
            raise TemplateError(f"{self.key} needs: {', '.join(missing)}")
        values = {p: str(context[p]) for p in self.placeholders}
        for name, table in self.lookups.get(language, {}).items():
            source = {"screening_name": "screening_type", "next_step": "pathway_id"}[name]
            if values.get(source) not in table:
                raise TemplateError(f"{self.key}: no {name} for {values.get(source)}")
            values[name] = table[values[source]]
        parts = {}
        for part in self.part_order:
            text = self.languages[language][part]
            unknown = set(_FIELD.findall(text)) - set(values)
            if unknown:
                raise TemplateError(f"{self.key}: unknown fields {unknown}")
            parts[part] = text.format_map(values)
        return {
            "template_id": self.id,
            "template_version": self.version,
            "language": language,
            "status": self.status,
            "review_note": self.review_note,
            "parts": parts,
            "text": " ".join(parts[p] for p in self.part_order),
        }


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TemplateLibrary:
    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self.data_dir = data_dir
        self._by_key: dict[str, Template] = {}
        for f in sorted(data_dir.glob("*@*.json")):
            t = Template.model_validate(json.loads(f.read_text("utf-8")))
            if f.stem != t.key:
                raise ValueError(f"{f.name}: file name must be {t.key}.json")
            for lang in LANGUAGES:
                if lang not in t.languages or set(t.languages[lang]) != set(t.part_order):
                    raise ValueError(f"{t.key}: {lang} must define parts {t.part_order}")
            self._by_key[t.key] = t

    def all(self) -> list[Template]:
        return list(self._by_key.values())

    def get(self, template_id: str, version: str | None = None) -> Template | None:
        if version:
            return self._by_key.get(f"{template_id}@{version}")
        hits = [t for t in self._by_key.values() if t.id == template_id]
        return max(hits, key=lambda t: tuple(int(x) for x in t.version.split("."))) if hits else None

    def latest(self) -> list[Template]:
        ids = sorted({t.id for t in self._by_key.values()})
        return [t for i in ids if (t := self.get(i))]

    def lock_mismatches(self, lock_path: Path = LOCK_PATH) -> list[str]:
        lock = json.loads(lock_path.read_text("utf-8")) if lock_path.exists() else {}
        out = []
        for key in self._by_key:
            h = _hash(self.data_dir / f"{key}.json")
            if lock.get(key) != h:
                out.append(f"{key}: not locked or changed after publishing")
        return out


@lru_cache(maxsize=1)
def default_templates() -> TemplateLibrary:
    return TemplateLibrary()


if __name__ == "__main__" and "--lock-new" in sys.argv:
    lib = TemplateLibrary()
    lock = json.loads(LOCK_PATH.read_text("utf-8")) if LOCK_PATH.exists() else {}
    for t in lib.all():
        h = _hash(DATA_DIR / f"{t.key}.json")
        if t.key in lock and lock[t.key] != h:
            sys.exit(f"refusing: {t.key} already published with a different hash")
        lock.setdefault(t.key, h)
    LOCK_PATH.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"locked {len(lock)} templates")
