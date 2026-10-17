"""Synthetic cohort generator (PLAN_FINAL.md section 18). Skeleton for week 1.

Creates fictional patients and screening results with injected failures, in the
same CSV format the importer accepts. Every row carries data_label=SIMULATED.

The failure rates below are TEST INJECTION SETTINGS chosen by the team to exercise
the workflow. They are not real-world statistics and must never be presented as such.
All figures shown in the demo come from our own runs on this data.

Usage:
  python -m loopcloser.synth.generator --n 1000 --seed 42 --out ../data/synthetic
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

LABEL = "SIMULATED"
DISCLAIMER = "SIMULATED, not clinical evidence. All people and records are fictional."

COLUMNS = [
    "record_id",
    "participant_id",
    "masked_name",
    "age_band",
    "location",
    "language",
    "phone",
    "contact_pref",
    "comorbidity",
    "screening_type",
    "result",
    "severity",
    "screened_at",
    "deadline",
    "owner",
    "status",
    "appointment_at",
    "evidence_ref",
    "red_flag",
    "barrier",
    "scenario",
    "data_label",
]

# Fictional, generic values only.
FIRST_NAMES = [
    "Maria",
    "Jose",
    "Ana",
    "Juan",
    "Rosa",
    "Pedro",
    "Luz",
    "Carlo",
    "Grace",
    "Mark",
    "Joy",
    "Ramon",
    "Liza",
    "Paolo",
    "Nina",
    "Ben",
    "Cora",
    "Dante",
    "Elena",
    "Rey",
]
LAST_INITIALS = list("ABCDEGLMNPRSTV")
LOCATIONS = ["Site A", "Site B", "Site C", "Site D", "Site E"]
AGE_BANDS = ["18-29", "30-39", "40-49", "50-59", "60-69", "70+"]
STAFF = ["worker-01", "worker-02", "worker-03", "coord-01", "coord-02"]
SUPPORTED_LANGS = ["en", "fil"]
ASSIST_LANGS = ["ceb", "ilo", "hil"]  # known languages that need a navigator

# (screening_type, result, severity)
RESULT_MIX = [
    ("fit", "positive", "abnormal"),
    ("bp", "elevated", "abnormal"),
    ("cervical", "abnormal", "abnormal"),
    ("generic", "abnormal", "abnormal"),
    ("generic", "borderline", "borderline"),
    ("bp", "borderline", "borderline"),
]


@dataclass
class InjectionRates:
    """Share of the cohort that gets each injected failure. Test settings, not statistics."""

    invalid_phone: float = 0.12
    no_appointment: float = 0.15
    no_show: float = 0.08
    transport_barrier: float = 0.10
    language_assistance: float = 0.06
    overdue: float = 0.05
    urgent: float = 0.03


@dataclass
class Cohort:
    seed: int
    n: int
    anchor_date: str
    rates: InjectionRates
    rows: list[dict] = field(default_factory=list)

    def manifest(self) -> dict:
        counts: dict[str, int] = {}
        for r in self.rows:
            for tag in filter(None, r["scenario"].split("|")):
                counts[tag] = counts.get(tag, 0) + 1
        return {
            "data_label": LABEL,
            "disclaimer": DISCLAIMER,
            "seed": self.seed,
            "n_patients": self.n,
            "n_rows": len(self.rows),
            "anchor_date": self.anchor_date,
            "injection_rates": asdict(self.rates),
            "injection_rates_note": "Team-chosen test settings, not real-world statistics.",
            "scenario_counts": dict(sorted(counts.items())),
        }


def _pick(rng: random.Random, n: int, rate: float, pool: list[int] | None = None) -> set[int]:
    pool = list(range(n)) if pool is None else pool
    return set(rng.sample(pool, min(len(pool), round(n * rate))))


def generate(
    n: int = 1000,
    seed: int = 42,
    anchor: date = date(2026, 10, 1),
    rates: InjectionRates | None = None,
    edge_cases: bool = True,
) -> Cohort:
    rates = rates or InjectionRates()
    rng = random.Random(seed)
    idx = list(range(n))
    invalid_phone = _pick(rng, n, rates.invalid_phone)
    no_appt = _pick(rng, n, rates.no_appointment)
    with_appt = [i for i in idx if i not in no_appt]
    no_show = _pick(rng, n, rates.no_show, with_appt)
    transport = _pick(rng, n, rates.transport_barrier)
    lang_assist = _pick(rng, n, rates.language_assistance)
    overdue = _pick(rng, n, rates.overdue)
    urgent = _pick(rng, n, rates.urgent)

    rows = []
    for i in idx:
        stype, result, severity = rng.choice(RESULT_MIX)
        tags = []
        if i in urgent:
            severity = "critical"
            tags.append("urgent")
        if i in overdue:
            screened = anchor - timedelta(days=rng.randint(45, 120))
            tags.append("overdue")
        else:
            screened = anchor - timedelta(days=rng.randint(0, 10))
        if i in invalid_phone:
            phone = rng.choice(["", "12345", "+63900"])
            tags.append("invalid_phone")
        else:
            phone = f"+639000{rng.randint(0, 999999):06d}"  # fake range; nothing is ever sent
        lang = rng.choice(ASSIST_LANGS) if i in lang_assist else rng.choice(SUPPORTED_LANGS)
        if i in lang_assist:
            tags.append("language_assistance")
        appt = ""
        status = "new"
        if i in no_appt:
            tags.append("no_appointment")
        else:
            appt = (screened + timedelta(days=rng.randint(3, 20))).isoformat()
            status = "scheduled"
        if i in no_show:
            status = "no_show"
            tags.append("no_show")
        barrier = ""
        if i in transport:
            barrier = "transport"
            tags.append("transport_barrier")
        owner = rng.choice(STAFF) if (severity == "critical" or rng.random() < 0.8) else ""
        rows.append(
            {
                "record_id": f"R-{i + 1:06d}",
                "participant_id": f"P-{i + 1:06d}",
                "masked_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_INITIALS)}.",
                "age_band": rng.choice(AGE_BANDS),
                "location": rng.choice(LOCATIONS),
                "language": lang,
                "phone": phone,
                "contact_pref": rng.choice(["sms", "call", "chw_visit"]),
                "comorbidity": "yes" if rng.random() < 0.2 else "no",
                "screening_type": stype,
                "result": result,
                "severity": severity,
                "screened_at": screened.isoformat(),
                "deadline": "",
                "owner": owner,
                "status": status,
                "appointment_at": appt,
                "evidence_ref": "",
                "red_flag": "no",
                "barrier": barrier,
                "scenario": "|".join(tags),
                "data_label": LABEL,
            }
        )
    if edge_cases:
        rows.extend(_edge_cases(rows, anchor))
    return Cohort(seed=seed, n=n, anchor_date=anchor.isoformat(), rates=rates, rows=rows)


def _edge_cases(rows: list[dict], anchor: date) -> list[dict]:
    """Hand-made edge cases from the plan. Some are meant to fail validation."""
    base = dict(rows[0])
    d = anchor.isoformat()

    def mk(n: int, **kw) -> dict:
        r = {
            **base,
            "record_id": f"E-{n:03d}",
            "participant_id": f"P-E{n:03d}",
            "screened_at": d,
            "deadline": "",
            "status": "new",
            "appointment_at": "",
            "evidence_ref": "",
            "red_flag": "no",
            "barrier": "",
            "owner": "coord-01",
            "data_label": LABEL,
        }
        r.update(kw)
        return r

    return [
        mk(1, phone="", contact_pref="chw_visit", scenario="edge_no_phone"),
        {**rows[1], "record_id": "E-002", "scenario": "edge_duplicate"},  # same participant/type/date as R-000002
        mk(3, deadline=(anchor - timedelta(days=5)).isoformat(), scenario="edge_wrong_deadline"),
        mk(4, status="declined", scenario="edge_refusal"),
        mk(5, scenario="edge_staff_override"),
        mk(6, status="completed", appointment_at="", evidence_ref="", scenario="edge_completed_elsewhere"),
        mk(7, severity="critical", owner="", red_flag="yes", scenario="edge_critical_no_owner"),
        mk(
            8,
            screening_type="symptom",
            result="new_symptom",
            severity="abnormal",
            red_flag="yes",
            scenario="edge_red_flag",
        ),
    ]


def write(cohort: Cohort, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "synthetic_cohort_SIMULATED.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(cohort.rows)
    man = out / "manifest_SIMULATED.json"
    man.write_text(json.dumps(cohort.manifest(), indent=2) + "\n", "utf-8")
    return csv_path, man


def main() -> None:
    ap = argparse.ArgumentParser(description=DISCLAIMER)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("../data/synthetic"))
    a = ap.parse_args()
    c = generate(a.n, a.seed)
    paths = write(c, a.out)
    print(f"{DISCLAIMER}\nwrote {paths[0]} ({len(c.rows)} rows) and {paths[1]}")


if __name__ == "__main__":
    main()
