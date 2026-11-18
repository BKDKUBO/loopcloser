import pytest

from loopcloser.domain import commands as cmd
from loopcloser.domain.case import project
from loopcloser.domain.errors import Conflict, GuardViolation
from loopcloser.domain.events import AUTOMATION_ACTOR, SYSTEM_ACTOR
from loopcloser.domain.states import CaseState as S
from loopcloser.domain.states import allowed_targets

from .conftest import NOW, screening


def _open(repo, lib, actor, **kw):
    owner = kw.pop("owner", "worker-01")
    s = screening(**kw)
    pw = lib.match(s["screening_type"], s["result"], s["severity"])
    return cmd.open_case(repo, case_id="C-1", screening=s, pathway=pw, actor=actor, owner=owner, now=NOW)


def _walk_to(repo, actor, *targets):
    for t in targets:
        payload = {"source": "understanding_check"} if t == S.UNDERSTANDING_CONFIRMED else {}
        cmd.transition(repo, "C-1", t, actor=actor, payload=payload, now=NOW)


def test_open_case_uses_pathway_and_deadline(repo, lib, coord):
    v = _open(repo, lib, coord)
    assert v.state == S.NEW_RESULT
    assert v.pathway_id == "fit-positive" and v.pathway_version == "1.0.0"
    assert v.pathway_signoff_status == "pending_clinical_signoff"
    assert "colonoscopy" in v.next_action.lower()
    assert str(v.due_date) == "2026-11-09"  # screened + 30 day configurable default


def test_happy_path_to_close_with_evidence(repo, lib, coord, supervisor):
    _open(repo, lib, coord)
    _walk_to(
        repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED, S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED
    )
    v = cmd.close_case(
        repo, "C-1", actor=supervisor, closure_reason="care completed", evidence_ref="visit:V-9", sign_off=True, now=NOW
    )
    assert v.state == S.CLOSED and v.closure_evidence == "visit:V-9"
    assert v.signed_off_by == "sup-01 (supervisor)"
    assert len(repo.load_events("C-1")) == 7


def test_cannot_skip_steps(repo, lib, coord):
    _open(repo, lib, coord)
    with pytest.raises(GuardViolation) as e:
        cmd.transition(repo, "C-1", S.ACTION_SCHEDULED, actor=coord, now=NOW)
    assert e.value.rule_id == "SM-1"


def test_transition_cannot_close(repo, lib, coord):
    _open(repo, lib, coord)
    _walk_to(
        repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED, S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED
    )
    with pytest.raises(GuardViolation) as e:
        cmd.transition(repo, "C-1", S.CLOSED, actor=coord, now=NOW)
    assert e.value.rule_id == "CLOSE-1"


def test_close_needs_reason_evidence_and_signoff(repo, lib, coord, supervisor):
    """Rule CLOSE-1: evidence AND a sign-off. Either alone is refused."""
    _open(repo, lib, coord)
    _walk_to(
        repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED, S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED
    )
    for kw in (
        {},
        {"sign_off": True},  # sign-off without evidence
        {"evidence_ref": "visit:V-9"},  # evidence without sign-off
        {"evidence_ref": "v", "sign_off": True},  # a one-letter reference is not evidence
    ):
        with pytest.raises(GuardViolation) as e:
            cmd.close_case(repo, "C-1", actor=supervisor, closure_reason="done", now=NOW, **kw)
        assert e.value.rule_id == "CLOSE-1", kw
    with pytest.raises(GuardViolation):
        cmd.close_case(
            repo, "C-1", actor=supervisor, closure_reason="", evidence_ref="visit:V-9", sign_off=True, now=NOW
        )
    assert repo.get_case("C-1").state == S.VISIT_COMPLETED
    v = cmd.close_case(
        repo, "C-1", actor=supervisor, closure_reason="done", evidence_ref="visit:V-9", sign_off=True, now=NOW
    )
    assert v.signed_off_by == "sup-01 (supervisor)" and v.closure_evidence == "visit:V-9"


def test_coordinator_cannot_sign_off_a_closure(repo, lib, coord):
    """Rule CLOSE-2: the supervisor is the clinical sign-off. A coordinator prepares the evidence."""
    _open(repo, lib, coord)
    _walk_to(
        repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED, S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED
    )
    with pytest.raises(GuardViolation) as e:
        cmd.close_case(
            repo, "C-1", actor=coord, closure_reason="done", evidence_ref="visit:V-9", sign_off=True, now=NOW
        )
    assert e.value.rule_id == "CLOSE-2"


def test_worker_and_automation_cannot_close(repo, lib, coord, worker):
    _open(repo, lib, coord)
    _walk_to(
        repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED, S.UNDERSTANDING_CONFIRMED, S.ACTION_SCHEDULED, S.VISIT_COMPLETED
    )
    with pytest.raises(GuardViolation) as e:
        cmd.close_case(repo, "C-1", actor=worker, closure_reason="x", evidence_ref="v", now=NOW)
    assert e.value.rule_id == "CLOSE-2"
    with pytest.raises(GuardViolation) as e:
        cmd.close_case(repo, "C-1", actor=SYSTEM_ACTOR, closure_reason="x", evidence_ref="v", now=NOW)
    assert e.value.rule_id == "CLOSE-1"


def test_message_never_moves_past_patient_notified(repo, lib, coord):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED)
    kw = dict(channel="sms", template_id="sms-minimal", template_version="1.0.0", language="fil", now=NOW)
    v = cmd.record_notification(repo, "C-1", status="delivered", actor=AUTOMATION_ACTOR, **kw)
    assert v.state == S.PATIENT_NOTIFIED
    v = cmd.record_notification(repo, "C-1", status="opened", actor=AUTOMATION_ACTOR, **kw)
    assert v.state == S.PATIENT_NOTIFIED
    with pytest.raises(GuardViolation) as e:
        cmd.transition(
            repo, "C-1", S.UNDERSTANDING_CONFIRMED, actor=coord, payload={"source": "message_opened"}, now=NOW
        )
    assert e.value.rule_id == "MSG-1"


def test_automation_can_only_escalate(repo, lib, coord):
    _open(repo, lib, coord)
    with pytest.raises(GuardViolation) as e:
        cmd.transition(repo, "C-1", S.REVIEWED, actor=AUTOMATION_ACTOR, now=NOW)
    assert e.value.rule_id == "AUTO-1"
    v = cmd.transition(repo, "C-1", S.ESCALATED, actor=AUTOMATION_ACTOR, payload={"reason": "Day 10"}, now=NOW)
    assert v.state == S.ESCALATED and v.escalation_level == 1


def test_exception_states_need_fields(repo, lib, coord):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED)
    with pytest.raises(GuardViolation) as e:
        cmd.transition(repo, "C-1", S.UNABLE_TO_REACH, actor=coord, payload={"reason": "no answer"}, now=NOW)
    assert e.value.rule_id == "SM-2"
    v = cmd.transition(
        repo,
        "C-1",
        S.UNABLE_TO_REACH,
        actor=coord,
        payload={"reason": "no answer", "escalation_date": "2026-10-20"},
        now=NOW,
    )
    assert v.state == S.UNABLE_TO_REACH


def test_no_show_only_after_scheduling():
    assert S.NO_SHOW not in allowed_targets(S.NEW_RESULT)
    assert S.NO_SHOW in allowed_targets(S.ACTION_SCHEDULED)
    assert allowed_targets(S.CLOSED) == frozenset()


def test_urgent_case_needs_owner(repo, lib, coord):
    _open(repo, lib, coord, severity="critical", owner=None)
    v = repo.get_case("C-1")
    assert v.clinical_urgency == "urgent" and "urgent_without_owner" in v.data_quality
    cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    with pytest.raises(GuardViolation) as e:
        cmd.transition(repo, "C-1", S.PATIENT_NOTIFIED, actor=coord, now=NOW)
    assert e.value.rule_id == "OWN-1"
    cmd.assign(repo, "C-1", actor=coord, owner="worker-02", now=NOW)
    assert cmd.transition(repo, "C-1", S.PATIENT_NOTIFIED, actor=coord, now=NOW).state == S.PATIENT_NOTIFIED


def test_failed_contacts_escalate(repo, lib, coord, worker):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED)
    for _ in range(2):
        v = cmd.log_contact_attempt(repo, "C-1", channel="call", result="no_answer", actor=worker, now=NOW)
    assert v.state == S.REVIEWED
    v = cmd.log_contact_attempt(repo, "C-1", channel="call", result="no_answer", actor=worker, now=NOW)
    assert v.state == S.ESCALATED and v.failed_contact_attempts == 3
    assert repo.load_events("C-1")[-1].rule_id == "ESC-1"


def test_red_flag_pauses_automation_and_needs_human(repo, lib, coord, supervisor):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED)
    v = cmd.report_red_flag(repo, "C-1", actor=coord, source="patient", code="new_symptoms", now=NOW)
    assert v.state == S.HUMAN_TASK_OPEN and v.automation_paused and v.clinical_urgency == "urgent"
    kinds = [e.payload.get("to") for e in repo.load_events("C-1")[-2:]]
    assert kinds == ["automation_paused", "human_task_open"]
    with pytest.raises(GuardViolation) as e:
        cmd.record_notification(
            repo,
            "C-1",
            status="sent",
            channel="sms",
            template_id="reminder",
            template_version="1.0.0",
            language="en",
            actor=AUTOMATION_ACTOR,
            now=NOW,
        )
    assert e.value.rule_id == "RF-1"
    with pytest.raises(GuardViolation):
        cmd.transition(repo, "C-1", S.RESOLVED_BY_HUMAN, actor=AUTOMATION_ACTOR, now=NOW)
    with pytest.raises(GuardViolation):  # still open red flag
        cmd.resume_automation(repo, "C-1", actor=supervisor, reason="ok", now=NOW)
    cmd.transition(repo, "C-1", S.CLINICIAN_CONTACTED, actor=coord, now=NOW)
    cmd.transition(repo, "C-1", S.RESOLVED_BY_HUMAN, actor=coord, now=NOW)
    with pytest.raises(GuardViolation):  # coordinator cannot resume
        cmd.resume_automation(repo, "C-1", actor=coord, reason="ok", now=NOW)
    v = cmd.resume_automation(repo, "C-1", actor=supervisor, reason="clinician reviewed", now=NOW)
    assert not v.automation_paused


def test_red_flag_at_intake(repo, lib, coord):
    v = _open(repo, lib, coord, red_flag=True)
    assert v.state == S.HUMAN_TASK_OPEN and v.automation_paused


def test_symptom_pathway_routes_to_red_flag(repo, lib, coord):
    v = _open(repo, lib, coord, screening_type="symptom", result="new_symptom")
    assert v.pathway_id == "new-symptoms" and v.state == S.HUMAN_TASK_OPEN


def test_event_log_is_source_of_truth(repo, lib, coord):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED)
    cmd.add_note(repo, "C-1", actor=coord, text="called, will book", now=NOW)
    assert repo.get_case("C-1").to_doc() == project(repo.load_events("C-1")).to_doc()
    assert [e.seq for e in repo.load_events("C-1")] == [1, 2, 3, 4]


def test_append_only_and_optimistic_concurrency(repo, lib, coord):
    _open(repo, lib, coord)
    events = repo.load_events("C-1")
    with pytest.raises(Conflict):
        repo.append("C-1", events, 0, repo.get_case("C-1"))  # rewrite history
    assert not hasattr(repo, "update_event") and not hasattr(repo, "delete_event")
    with pytest.raises(Exception):
        events[0].payload = {}  # events are frozen


def test_project_rejects_gaps(repo, lib, coord):
    _open(repo, lib, coord)
    _walk_to(repo, coord, S.REVIEWED, S.PATIENT_NOTIFIED)
    ev = repo.load_events("C-1")
    with pytest.raises(ValueError):
        project([ev[0], ev[2]])
