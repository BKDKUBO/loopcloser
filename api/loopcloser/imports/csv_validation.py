"""CSV upload validation (PLAN_FINAL.md section 14).

Returns a preview with row-level errors and warnings. Only rows without errors are
importable. An error CSV (original columns plus the issues) can be downloaded.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

REQUIRED = ["record_id", "participant_id", "screening_type", "result", "severity", "screened_at", "language"]
SEVERITIES = {"normal", "borderline", "abnormal", "critical"}
SCREENING_TYPES = {"fit", "bp", "cervical", "generic", "symptom"}
SUPPORTED_LANGS = {"en", "fil"}
ASSIST_LANGS = {"ceb", "ilo", "hil", "war", "pam", "bcl", "ar"}  # known, needs a navigator
STATUSES = {"new", "scheduled", "completed", "closed", "no_show", "declined"}
PHONE_RE = re.compile(r"^\+639\d{9}$")
MAX_ROWS = 20_000


@dataclass
class RowResult:
    line: int
    row: dict[str, str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class ValidationReport:
    columns: list[str]
    rows: list[RowResult]
    file_errors: list[str] = field(default_factory=list)

    @property
    def valid_rows(self) -> list[dict[str, str]]:
        return [r.row for r in self.rows if r.valid]

    def summary(self) -> dict:
        return {
            "total_rows": len(self.rows),
            "valid_rows": sum(r.valid for r in self.rows),
            "rows_with_errors": sum(not r.valid for r in self.rows),
            "rows_with_warnings": sum(bool(r.warnings) for r in self.rows),
            "file_errors": self.file_errors,
        }

    def error_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["line", *self.columns, "errors", "warnings"])
        for r in self.rows:
            if r.errors or r.warnings:
                w.writerow(
                    [r.line, *[r.row.get(c, "") for c in self.columns], "; ".join(r.errors), "; ".join(r.warnings)]
                )
        return buf.getvalue()


def _date(value: str) -> date | None:
    try:
        d = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    return d if d.year >= 1900 else None


def validate_csv(text: str, *, today: date | None = None) -> ValidationReport:
    today = today or date.today()
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    columns = list(reader.fieldnames or [])
    missing_cols = [c for c in REQUIRED if c not in columns]
    report = ValidationReport(columns=columns, rows=[])
    if missing_cols:
        report.file_errors.append(f"missing required columns: {', '.join(missing_cols)}")
        return report

    seen_ids: dict[str, int] = {}
    seen_keys: dict[tuple[str, str, str], int] = {}
    for n, raw in enumerate(reader, start=2):  # line 1 is the header
        if len(report.rows) >= MAX_ROWS:
            report.file_errors.append(f"file has more than {MAX_ROWS} rows; the rest was skipped")
            break
        row = {k: (v or "").strip() for k, v in raw.items() if k is not None}
        r = RowResult(line=n, row=row)
        for c in REQUIRED:
            if not row.get(c):
                r.errors.append(f"missing {c}")
        sev = row.get("severity", "")
        if sev and sev not in SEVERITIES:
            r.errors.append(f"invalid severity '{sev}'")
        st = row.get("screening_type", "")
        if st and st not in SCREENING_TYPES:
            r.errors.append(f"unknown screening type '{st}'")
        status = row.get("status", "") or "new"
        if status not in STATUSES:
            r.errors.append(f"unknown status '{status}'")

        screened = _date(row.get("screened_at", "")) if row.get("screened_at") else None
        if row.get("screened_at") and screened is None:
            r.errors.append("impossible screened_at date")
        elif screened and screened > today:
            r.errors.append("screened_at is in the future")
        if row.get("deadline"):
            dl = _date(row["deadline"])
            if dl is None:
                r.errors.append("impossible deadline date")
            elif screened and dl < screened:
                r.errors.append("deadline is before the screening date")
        if row.get("appointment_at") and _date(row["appointment_at"]) is None:
            r.errors.append("impossible appointment date")

        lang = row.get("language", "")
        if lang and lang not in SUPPORTED_LANGS:
            if lang in ASSIST_LANGS:
                r.warnings.append(f"language '{lang}' needs a navigator")
            else:
                r.errors.append(f"unknown language '{lang}'")

        rid = row.get("record_id", "")
        if rid:
            if rid in seen_ids:
                r.errors.append(f"duplicate record_id (first on line {seen_ids[rid]})")
            else:
                seen_ids[rid] = n
        key = (row.get("participant_id", ""), st, row.get("screened_at", ""))
        if all(key):
            if key in seen_keys:
                r.warnings.append(f"possible duplicate of line {seen_keys[key]} (same participant, test and date)")
            else:
                seen_keys[key] = n

        if status == "completed" and not row.get("appointment_at"):
            r.errors.append("completed with no appointment")
        if status == "closed" and not row.get("evidence_ref"):
            r.errors.append("closed without evidence")
        if sev == "critical" and not row.get("owner"):
            r.errors.append("critical result with no owner")
        phone = row.get("phone", "")
        if "phone" in columns and not PHONE_RE.match(phone):
            r.warnings.append("no valid phone; use a call-back or community health worker visit")
        if sev == "normal":
            r.warnings.append("normal result; no follow-up case will be opened")
        report.rows.append(r)
    return report
