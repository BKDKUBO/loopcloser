from datetime import timedelta

import pytest

from loopcloser.domain import commands as cmd
from loopcloser.domain import ladder
from loopcloser.domain.errors import GuardViolation
from loopcloser.domain.events import AUTOMATION_ACTOR
from loopcloser.domain.next_action import recommend
from loopcloser.domain.states import CaseState as S
from loopcloser.templates.library import TemplateError, TemplateLibrary, default_templates

from .conftest import NOW, screening

DAY0 = NOW.date()


def _open(repo, lib, actor, case_id="C-1", **kw):
    owner = kw.pop("owner", "w1")
    s = screening(**kw)
    pw = lib.match(s["screening_type"], s["result"], s["severity"])
    return cmd.open_case(repo, case_id=case_id, screening=s, pathway=pw, actor=actor, owner=owner, now=NOW)


def _run(repo, day):
    return ladder.run_case(repo, "C-1", today=DAY0 + timedelta(days=day), now=NOW + timedelta(days=day))


def test_default_ladder_days():
    assert [(s.day, s.id) for s in ladder.DEFAULT_LADDER] == [
        (0, "upload"),
        (1, "review"),
        (2, "contact"),
        (4, "reminder"),
        (7, "chw"),
        (10, "supervisor"),
        (14, "unresolved_review"),
    ]


def test_ladder_climbs_to_supervisor(repo, lib, coord):
    _open(repo, lib, coord)
    assert _run(repo, 0) == []
    assert [a.split(":")[0] for a in _run(repo, 1)] == ["review"]
    assert [a.split(":")[0] for a in _run(repo, 2)] == ["contact"]
    assert _run(repo, 2) == []  # each step only once
    cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    acts = _run(repo, 4)
    assert acts and acts[0].startswith("reminder")
    events = repo.load_events("C-1")
    sent = [e for e in events if e.type == "notification_status"]
    assert sent and sent[-1].payload["template_id"] == "reminder" and sent[-1].actor.kind == "automation"
    _run(repo, 7)
    v = repo.get_case("C-1")
    assert "chw" in v.ladder_steps and v.state == S.REVIEWED
    _run(repo, 10)
    v = repo.get_case("C-1")
    assert v.state == S.ESCALATED and v.escalation_level == 1
    _run(repo, 14)
    assert "unresolved_review" in repo.get_case("C-1").ladder_steps
    status = ladder.status(repo.get_case("C-1"), DAY0 + timedelta(days=14))
    assert all(s["state"] == "done" for s in status)


def test_ladder_skips_steps_no_longer_needed(repo, lib, coord):
    _open(repo, lib, coord)
    for t, p in [
        (S.REVIEWED, {}),
        (S.PATIENT_NOTIFIED, {}),
        (S.UNDERSTANDING_CONFIRMED, {"source": "staff_confirmed"}),
        (S.ACTION_SCHEDULED, {}),
    ]:
        cmd.transition(repo, "C-1", t, actor=coord, payload=p, now=NOW)
    cmd.log_contact_attempt(repo, "C-1", channel="call", result="reached", actor=coord, now=NOW)
    acts = _run(repo, 14)
    assert [a.split(":")[0] for a in acts] == ["unresolved_review"]
    assert repo.get_case("C-1").state == S.ACTION_SCHEDULED
    states = {s["id"]: s["state"] for s in ladder.status(repo.get_case("C-1"), DAY0 + timedelta(days=14))}
    assert states["review"] == "not needed" and states["supervisor"] == "not needed"
    assert states["unresolved_review"] == "done"


def test_ladder_stops_for_red_flag(repo, lib, coord):
    _open(repo, lib, coord)
    cmd.report_red_flag(repo, "C-1", actor=coord, source="patient", code="x", now=NOW)
    assert _run(repo, 14) == []


def test_invalid_phone_skips_sms(repo, lib, coord):
    _open(repo, lib, coord, phone_valid=False)
    cmd.transition(repo, "C-1", S.REVIEWED, actor=coord, now=NOW)
    acts = _run(repo, 4)
    assert any("No valid phone" in a for a in acts)
    assert not [e for e in repo.load_events("C-1") if e.type == "notification_status"]


def test_ladder_config():
    steps = ladder.load_ladder('[{"day": 0, "id": "upload"}, {"day": 3, "id": "review"}]')
    assert [s.day for s in steps] == [0, 3]
    with pytest.raises(ValueError):
        ladder.load_ladder('[{"day": 1, "id": "send_police"}]')


def test_templates_bilingual_and_pending_review():
    lib = default_templates()
    assert lib.lock_mismatches() == []
    ids = {t.id for t in lib.latest()}
    assert {"result-notice", "reminder", "sms-minimal", "emergency-guidance", "booking-confirmation"} <= ids
    for t in lib.all():
        assert t.status == "pending_review" and set(t.languages) == {"en", "fil"}


def test_result_notice_has_four_parts_and_every_pathway(lib):
    t = default_templates().get("result-notice")
    for p in lib.latest():
        for lang in ("en", "fil"):
            stype = {
                "fit-positive": "fit",
                "bp-elevated": "bp",
                "cervical-abnormal": "cervical",
                "new-symptoms": "symptom",
            }.get(p.id, "generic")
            out = t.render(
                lang, {"screening_type": stype, "pathway_id": p.id, "due_date": "2026-11-01", "clinic_phone": "000"}
            )
            assert list(out["parts"]) == [
                "what_happened",
                "what_it_does_not_mean",
                "what_to_do_next",
                "when_to_seek_urgent_help",
            ]
            assert "911" in out["text"]


def test_template_render_rejects_missing_fields():
    t = default_templates().get("booking-confirmation")
    with pytest.raises(TemplateError):
        t.render("en", {"clinic_phone": "000"})
    with pytest.raises(TemplateError):
        t.render("ceb", {"clinic_phone": "000", "appointment_date": "x", "clinic": "y"})


def test_changed_template_detected(tmp_path):
    import json
    import shutil

    from loopcloser.templates.library import DATA_DIR, LOCK_PATH

    shutil.copytree(DATA_DIR, tmp_path / "d")
    f = tmp_path / "d" / "reminder@1.0.0.json"
    doc = json.loads(f.read_text())
    doc["languages"]["en"]["body"] = "Take this medicine now."
    f.write_text(json.dumps(doc))
    assert TemplateLibrary(tmp_path / "d").lock_mismatches(LOCK_PATH)


def test_notification_requires_template(repo, lib, coord):
    _open(repo, lib, coord)
    with pytest.raises(GuardViolation) as e:
        cmd.record_notification(
            repo,
            "C-1",
            status="sent",
            channel="sms",
            template_id="gemini-draft",
            template_version="1",
            language="en",
            actor=AUTOMATION_ACTOR,
            now=NOW,
        )
    assert e.value.rule_id == "MSG-3"


def test_recommended_action(repo, lib, coord):
    v = _open(repo, lib, coord, owner=None)
    assert recommend(v)["kind"] == "assign"
    v = cmd.assign(repo, "C-1", actor=coord, owner="w1", now=NOW)
    assert recommend(v) == {"label": "Review the result", "kind": "transition", "target": "reviewed"}
    v = cmd.report_red_flag(repo, "C-1", actor=coord, source="staff", code="x", now=NOW)
    assert recommend(v)["target"] == "clinician_contacted"
