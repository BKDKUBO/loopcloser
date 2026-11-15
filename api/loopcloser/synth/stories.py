"""Replay the scripted SIMULATED demo stories (synth/generator.py DEMO_STORIES) through the real domain
commands. Each step is back-dated to its story day and the escalation ladder runs once per simulated day,
so every event in the timeline was produced by the same guards and rules as a live case.

Names and phone numbers are fictional. They are returned separately (never stored on the case) so the
API can keep them in the server-only contacts store.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from ..domain import commands as cmd
from ..domain import ladder as ladder_mod
from ..domain.events import Actor
from ..domain.roles import Role
from ..domain.states import CaseState as S
from ..pathways.library import PathwayLibrary
from ..store.base import CaseRepository
from .generator import DEMO_STORIES, story_ids, story_phone

ACTORS = {
    "worker": Actor(id="demo-worker-01", role=Role.WORKER),
    "chw": Actor(id="demo-worker-02", role=Role.WORKER),
    "coord": Actor(id="demo-coord-01", role=Role.COORDINATOR),
    "sup": Actor(id="demo-sup-01", role=Role.SUPERVISOR),
}
# 01:00 UTC is 9:00 AM in Manila: story days start at the start of the clinic day.
_DAY_START = time(1, 0, tzinfo=UTC)


def _at(day0: date, day: int, i: int, now: datetime | None = None) -> datetime:
    """Back-dated event time: 9:00 AM Manila on the story day plus 20 minutes per step, never after now."""
    t = datetime.combine(day0 + timedelta(days=day), _DAY_START) + timedelta(minutes=20 * i)
    if now is not None and t > now:
        t = now - timedelta(minutes=2 * (20 - min(i, 19)))
    return t


def _step(repo: CaseRepository, case_id: str, step: tuple, day0: date, now: datetime, today: date) -> None:
    kind = step[1]
    actor = ACTORS[step[2]]
    if kind == "review":
        cmd.transition(repo, case_id, S.REVIEWED, actor=actor, now=now)
    elif kind in {"call", "visit"}:
        channel = "call" if kind == "call" else "chw_visit"
        cmd.log_contact_attempt(repo, case_id, channel=channel, result=step[3], actor=actor, now=now)
    elif kind == "notified":
        cmd.transition(repo, case_id, S.PATIENT_NOTIFIED, actor=actor, now=now, payload={"note": step[3]})
    elif kind == "understood":
        cmd.transition(
            repo, case_id, S.UNDERSTANDING_CONFIRMED, actor=actor, now=now, payload={"source": "staff_confirmed"}
        )
    elif kind == "book":
        appt = {"date": (day0 + timedelta(days=step[3])).isoformat(), "clinic": step[4]}
        cmd.transition(repo, case_id, S.ACTION_SCHEDULED, actor=actor, now=now, payload={"appointment": appt})
    elif kind == "message":
        v = repo.get_case(case_id)
        lang = v.language if v and v.language in {"en", "fil"} else "en"
        cmd.record_notification(
            repo,
            case_id,
            status="sent",
            channel="sms",
            template_id=step[3],
            template_version="1.0.0",
            language=lang,
            actor=actor,
            now=now,
        )
    elif kind == "visit_done":
        cmd.transition(repo, case_id, S.VISIT_COMPLETED, actor=actor, now=now)
    elif kind == "no_show":
        cmd.transition(repo, case_id, S.NO_SHOW, actor=actor, now=now, payload={"note": "Did not come to the visit"})
    elif kind == "declined":
        cmd.transition(repo, case_id, S.DECLINED, actor=actor, now=now, payload={"reason": step[3]})
    elif kind == "barrier":
        cmd.report_barrier(repo, case_id, actor=actor, barrier=step[3], now=now)
    elif kind == "red_flag":
        cmd.report_red_flag(repo, case_id, actor=actor, source="staff", code=step[3], now=now)
    elif kind == "close":
        ev = step[4]
        evidence = (
            {
                "visit_date": (day0 + timedelta(days=ev["visit_day"])).isoformat(),
                "facility": ev["facility"],
                "record_number": ev["record"],
            }
            if ev
            else None
        )
        cmd.close_case(
            repo,
            case_id,
            actor=actor,
            closure_reason=step[3],
            evidence=evidence,
            sign_off=evidence is None,
            now=now,
            today=today,
        )
    else:  # pragma: no cover - data error
        raise ValueError(f"unknown story step {kind}")


def play_stories(
    repo: CaseRepository,
    lib: PathwayLibrary,
    *,
    today: date,
    now: datetime | None = None,
    ladder: tuple[ladder_mod.Step, ...] = ladder_mod.DEFAULT_LADDER,
    skip: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Open and replay every story whose case id is not in skip. Returns {participant_id: {name, phone}}."""
    contacts: dict[str, dict[str, str]] = {}
    for st in DEMO_STORIES:
        case_id, pid = story_ids(st)
        contacts[pid] = {"name": st["name"], "phone": story_phone(st), "data_label": "SIMULATED"}
        if skip and case_id in skip:
            continue
        pw = lib.match(st["screening_type"], st["result"], st["severity"])
        if pw is None:  # pragma: no cover - data error
            raise ValueError(f"story {case_id} matches no pathway")
        day0 = today - timedelta(days=st["opened_days_ago"])
        phone = story_phone(st)
        cmd.open_case(
            repo,
            case_id=case_id,
            pathway=pw,
            actor=ACTORS["coord"],
            owner=st.get("owner") or None,
            synthetic=True,
            now=_at(day0, 0, 0, now),
            screening={
                "participant_id": pid,
                "screening_id": f"S-DEMO-{st['n']:02d}",
                "screening_type": st["screening_type"],
                "result": st["result"],
                "severity": st["severity"],
                "screened_at": (today - timedelta(days=st["screened_days_ago"])).isoformat(),
                "language": st["language"],
                "comorbidity": bool(st.get("comorbidity")),
                "location": st.get("location"),
                "age_band": st.get("age_band"),
                "phone_valid": bool(phone),
                "contact_consent": st.get("consent", "yes"),
            },
        )
        by_day: dict[int, list[tuple]] = {}
        for step in st["steps"]:
            by_day.setdefault(step[0], []).append(step)
        for d in range(0, st["opened_days_ago"] + 1):
            steps = by_day.get(d, [])
            ran_ladder = False
            for i, step in enumerate(steps, start=1):
                t = _at(day0, d, i, now)
                if step[1] == "ladder":
                    ladder_mod.run_case(repo, case_id, today=day0 + timedelta(days=d), now=t, ladder=ladder)
                    ran_ladder = True
                else:
                    _step(repo, case_id, step, day0, t, day0 + timedelta(days=d))
            if not ran_ladder:
                t = _at(day0, d, len(steps) + 1, now)
                ladder_mod.run_case(repo, case_id, today=day0 + timedelta(days=d), now=t, ladder=ladder)
    return contacts


def lead_story() -> dict[str, Any]:
    return next(s for s in DEMO_STORIES if s.get("lead"))
