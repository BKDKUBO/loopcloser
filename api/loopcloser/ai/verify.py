"""Check an AI draft against the case record before anyone sees it.

Every number and date in the draft must appear in the facts the model was given. Anything else (an invented
phone number, a wrong deadline, a made-up count) makes the draft unverified, and the API withholds its text.
Pure functions, no I/O. The check is deliberately strict: a false alarm only costs a regenerated draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan", "enero"),
            ("february", "feb", "pebrero"),
            ("march", "mar", "marso"),
            ("april", "apr", "abril"),
            ("may", "mayo"),
            ("june", "jun", "hunyo"),
            ("july", "jul", "hulyo"),
            ("august", "aug", "agosto"),
            ("september", "sep", "sept", "setyembre"),
            ("october", "oct", "oktubre"),
            ("november", "nov", "nobyembre"),
            ("december", "dec", "disyembre"),
        ]
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTH_DAY = re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE)
DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE
)
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,:]\d+)*(?![\w])")
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s+", re.MULTILINE)
WORD_NUMBERS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty".split()
    )
}
WORD_RE = re.compile(r"\b(" + "|".join(WORD_NUMBERS) + r")\b", re.IGNORECASE)
# Words that are numbers only by accident ("one of", "no one") are still checked: strict on purpose,
# except "one" which is too common in plain English to treat as a fact.
IGNORED_WORDS = {"one", "zero"}


@dataclass
class Verification:
    verified: bool
    checked: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"verified": self.verified, "checked": self.checked, "unsupported": self.unsupported}


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _flatten(v)]
    if isinstance(value, list | tuple | set):
        return [s for v in value for s in _flatten(v)]
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _norm_number(s: str) -> str:
    s = s.replace(",", "")
    if re.fullmatch(r"\d+(\.0+)?", s):
        return str(int(float(s)))
    return s


def allowed_from_facts(facts: dict[str, Any]) -> tuple[set[str], set[date]]:
    numbers: set[str] = set()
    dates: set[date] = set()
    for s in _flatten(facts):
        for m in ISO_DATE.finditer(s):
            try:
                dates.add(date(int(m[1]), int(m[2]), int(m[3])))
            except ValueError:
                pass
        for m in NUMBER.finditer(ISO_DATE.sub(" ", s)):
            numbers.add(_norm_number(m.group()))
        for m in WORD_RE.finditer(s):  # "on two different days" in a pathway allows "two" in the draft
            numbers.add(str(WORD_NUMBERS[m.group().lower()]))
    return numbers, dates


def _date_ok(month: int, day: int, year: int | None, dates: set[date]) -> bool:
    return any(d.month == month and d.day == day and (year is None or d.year == year) for d in dates)


def verify_draft(text: str, facts: dict[str, Any]) -> Verification:
    numbers, dates = allowed_from_facts(facts)
    checked: list[str] = []
    bad: list[str] = []
    rest = LIST_MARKER.sub("", text)

    def check_date(token: str, month: int, day: int, year: int | None) -> str:
        checked.append(token)
        if not _date_ok(month, day, year, dates):
            bad.append(token)
        return " "

    def iso(m: re.Match) -> str:
        return check_date(m.group(), int(m[2]), int(m[3]), int(m[1]))

    def month_day(m: re.Match) -> str:
        return check_date(m.group(), MONTHS[m[1].lower()], int(m[2]), int(m[3]) if m[3] else None)

    def day_month(m: re.Match) -> str:
        return check_date(m.group(), MONTHS[m[2].lower()], int(m[1]), int(m[3]) if m[3] else None)

    def slash(m: re.Match) -> str:
        # Ambiguous (11/12 could be Nov 12 or Dec 11): accept only if it matches a fact date read month-first.
        y = int(m[3]) if m[3] else None
        if y is not None and y < 100:
            y += 2000
        return (
            check_date(m.group(), int(m[1]), int(m[2]), y) if 1 <= int(m[1]) <= 12 else check_date(m.group(), 0, 0, y)
        )

    rest = ISO_DATE.sub(iso, rest)
    rest = MONTH_DAY.sub(month_day, rest)
    rest = DAY_MONTH.sub(day_month, rest)
    rest = SLASH_DATE.sub(slash, rest)
    for m in NUMBER.finditer(rest):
        tok = m.group()
        checked.append(tok)
        if _norm_number(tok) not in numbers:
            bad.append(tok)
    for m in WORD_RE.finditer(rest):
        w = m.group().lower()
        if w in IGNORED_WORDS:
            continue
        checked.append(m.group())
        if str(WORD_NUMBERS[w]) not in numbers:
            bad.append(m.group())
    return Verification(verified=not bad, checked=checked, unsupported=bad)
