import csv
import io

from loopcloser.imports.csv_validation import validate_csv
from loopcloser.synth.generator import COLUMNS, LABEL, generate, write


def _csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def test_generator_is_deterministic_and_labeled():
    a, b = generate(1000, 7), generate(1000, 7)
    assert a.rows == b.rows
    assert sum(r["record_id"].startswith("R-") for r in a.rows) == 1000
    assert all(r["data_label"] == LABEL for r in a.rows)
    m = a.manifest()
    assert m["data_label"] == "SIMULATED" and "not clinical evidence" in m["disclaimer"]


def test_injected_rates_are_exact():
    c = generate(1000, 42)
    counts = c.manifest()["scenario_counts"]
    assert counts["invalid_phone"] == 120
    assert counts["no_appointment"] == 150
    assert counts["no_show"] == 80
    assert counts["transport_barrier"] == 100
    assert counts["language_assistance"] == 60
    assert counts["overdue"] == 50
    assert counts["urgent"] == 30


def test_write(tmp_path):
    csv_path, man = write(generate(50, 1), tmp_path)
    assert "SIMULATED" in csv_path.name and man.exists()


def test_validator_catches_edge_cases():
    rep = validate_csv(_csv(generate(1000, 42).rows))
    by_id = {r.row["record_id"]: r for r in rep.rows}
    assert any("deadline is before" in e for e in by_id["E-003"].errors)
    assert any("completed with no appointment" in e for e in by_id["E-006"].errors)
    assert any("critical result with no owner" in e for e in by_id["E-007"].errors)
    assert any("possible duplicate" in w for w in by_id["E-002"].warnings)
    assert any("phone" in w for w in by_id["E-001"].warnings)
    assert rep.summary()["valid_rows"] >= 1000


def test_validator_row_errors_and_error_csv():
    text = (
        "record_id,participant_id,screening_type,result,severity,screened_at,language,status,owner\n"
        "R1,P1,fit,positive,severe,2026-10-01,en,new,w\n"
        "R1,P2,fit,positive,abnormal,2026-02-30,xx,closed,w\n"
        "R3,P3,bp,elevated,abnormal,2026-10-01,ceb,new,w\n"
    )
    rep = validate_csv(text)
    assert rep.rows[0].errors == ["invalid severity 'severe'"]
    errs = rep.rows[1].errors
    assert "impossible screened_at date" in errs and "unknown language 'xx'" in errs
    assert any("duplicate record_id" in e for e in errs) and "closed without evidence" in errs
    assert rep.rows[2].valid and "needs a navigator" in rep.rows[2].warnings[0]
    out = rep.error_csv()
    assert out.splitlines()[0].endswith("errors,warnings") and len(out.splitlines()) == 4


def test_missing_columns():
    rep = validate_csv("record_id,foo\n1,2\n")
    assert rep.file_errors and not rep.rows
