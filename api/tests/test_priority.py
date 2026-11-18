from datetime import date

import pytest

from loopcloser.domain import commands as cmd
from loopcloser.domain import priority as prio
from loopcloser.domain.errors import GuardViolation
from loopcloser.domain.states import CaseState as S

from .conftest import NOW, screening

TODAY = date(2026, 10, 17)


def _open(repo, lib, actor, barriers=None, owner="w1", **kw):
    s = screening(**kw)
    pw = lib.match(s["screening_type"], s["result"], s["severity"])
    return cmd.open_case(
        repo, case_id="C-1", screening=s, pathway=pw, actor=actor, owner=owner, barriers=barriers, now=NOW
    )


@pytest.mark.parametrize(
    "score,tier",
    [
        (0, "routine"),
        (2, "routine"),
        (3, "moderate"),
        (4, "moderate"),
        (5, "high"),
        (7, "high"),
        (8, "urgent"),
        (20, "urgent"),
    ],
)
def test_tier_boundaries(score, tier):
    assert prio.tier_for(score) == tier


def test_rule_points_match_plan():
    assert prio.POINTS == {
        "PRI-CRITICAL": 5,
        "PRI-RED-FLAG": 5,
        "PRI-OVERDUE": 4,
        "PRI-DUE-SOON": 3,
        "PRI-NO-APPT": 3,
        "PRI-MISSED": 2,
        "PRI-BARRIER": 2,
        "PRI-NO-CONTACT": 2,
        "PRI-COMORBID": 1,
        "PRI-LANGUAGE": 1,
    }


def test_example_from_plan_critical_plus_transport(repo, lib, coord):
    # Book the appointment and reach the patient so only critical + transport remain: High (7)
    v = _open(repo, lib, coord, severity="critical", barriers=["transport"])
    for t, p in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {}),
    ]:
        v = cmd.transition(repo, "C-1", t, actor=coord, payload=p, now=NOW)
    pr = prio.compute(v, TODAY)
    assert pr.score == 7 and pr.tier == "high"
    assert pr.explanation == "High (7): critical result (+5); transport, cost or work barrier (+2)."


def test_all_rules_can_fire(repo, lib, coord):
    v = _open(
        repo,
        lib,
        coord,
        severity="critical",
        barriers=["cost"],
        language="ceb",
        comorbidity=True,
        screened_at="2026-09-01",
    )
    cmd.report_red_flag(repo, "C-1", actor=coord, source="staff", code="x", now=NOW)
    v = repo.get_case("C-1")
    pr = prio.compute(v, TODAY)
    ids = {r["rule_id"] for r in pr.reasons}
    assert ids == {
        "PRI-CRITICAL",
        "PRI-RED-FLAG",
        "PRI-OVERDUE",
        "PRI-NO-APPT",
        "PRI-BARRIER",
        "PRI-NO-CONTACT",
        "PRI-COMORBID",
        "PRI-LANGUAGE",
    }
    assert pr.tier == "urgent"


def test_due_soon_and_missed(repo, lib, coord):
    v = _open(repo, lib, coord, screened_at="2026-09-19")  # FIT +30 days -> due 2026-10-19
    pr = prio.compute(v, TODAY)
    assert "PRI-DUE-SOON" in {r["rule_id"] for r in pr.reasons}
    for t, p in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {}),
        (S.NO_SHOW, {}),
    ]:
        v = cmd.transition(repo, "C-1", t, actor=coord, payload=p, now=NOW)
    assert "PRI-MISSED" in {r["rule_id"] for r in prio.compute(v, TODAY).reasons}


def test_language_and_digital_barriers_are_not_logistics(repo, lib, coord):
    v = _open(repo, lib, coord, barriers=["language", "digital"])
    assert "PRI-BARRIER" not in {r["rule_id"] for r in prio.compute(v, TODAY).reasons}


def test_closed_case_has_no_priority(repo, lib, coord, supervisor):
    _open(repo, lib, coord)
    for t, p in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {}),
        (S.VISIT_COMPLETED, {}),
    ]:
        cmd.transition(repo, "C-1", t, actor=coord, payload=p, now=NOW)
    v = cmd.close_case(
        repo, "C-1", actor=supervisor, closure_reason="done", evidence_ref="visit-1", sign_off=True, now=NOW
    )
    assert prio.compute(v, TODAY).score == 0


def test_override_rules(repo, lib, coord, supervisor):
    _open(repo, lib, coord)
    with pytest.raises(GuardViolation) as e:
        cmd.override_priority(repo, "C-1", actor=coord, tier="routine", reason="duplicate", note="dup", now=NOW)
    assert e.value.rule_id == "PRI-1"
    with pytest.raises(GuardViolation):
        cmd.override_priority(repo, "C-1", actor=supervisor, tier="routine", reason="because", note="x", now=NOW)
    v = cmd.override_priority(
        repo, "C-1", actor=supervisor, tier="routine", reason="duplicate", note="duplicate of C-9", now=NOW
    )
    pr = prio.compute(v, TODAY)
    assert pr.tier == "routine" and pr.computed_tier == "high"
    assert pr.override["by"] == "sup-01"
    v = cmd.override_priority(repo, "C-1", actor=supervisor, tier=None, reason="data_error", note="undo", now=NOW)
    assert v.priority_override is None


def test_cannot_lower_with_red_flag(repo, lib, coord, supervisor):
    _open(repo, lib, coord)
    cmd.report_red_flag(repo, "C-1", actor=coord, source="patient", code="x", now=NOW)
    with pytest.raises(GuardViolation) as e:
        cmd.override_priority(repo, "C-1", actor=supervisor, tier="high", reason="other", note="x", now=NOW)
    assert e.value.rule_id == "PRI-2"
    v = cmd.override_priority(
        repo, "C-1", actor=supervisor, tier="urgent", reason="worsening_symptoms", note="confirm", now=NOW
    )
    assert prio.compute(v, TODAY).tier == "urgent"


def test_barrier_report_and_resolve(repo, lib, coord, worker):
    _open(repo, lib, coord)
    with pytest.raises(GuardViolation):
        cmd.report_barrier(repo, "C-1", actor=worker, barrier="weather", now=NOW)
    v = cmd.report_barrier(repo, "C-1", actor=worker, barrier="transport", now=NOW)
    assert v.barriers_open == ["transport"]
    with pytest.raises(GuardViolation):
        cmd.resolve_barrier(repo, "C-1", actor=worker, barrier="transport", resolution=" ", now=NOW)
    v = cmd.resolve_barrier(repo, "C-1", actor=worker, barrier="transport", resolution="closer clinic", now=NOW)
    assert v.barriers_open == []
