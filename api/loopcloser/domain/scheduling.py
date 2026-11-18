"""Simulated appointment slots (rules APPT-1, APPT-2). No real clinic schedule is connected in this build.

Each fictional clinic offers Monday to Friday slots at 09:00, 10:00, 11:00 and 14:00 Manila time for the next 14
days after the (simulated) today, 2 patients per slot. A slot is full when that many open LoopCloser cases are
booked into it; bookings are counted from the case records (idx_slot), nothing else. The booked appointment is
stored on the case in the shape of a FHIR R4 Appointment, locally: it is never sent to any server.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")
CLINICS: dict[str, str] = {
    "SITE-A": "Site A rural health unit (fictional)",
    "SITE-B": "Site B rural health unit (fictional)",
    "SITE-C": "Site C health center (fictional)",
    "DISTRICT": "District hospital endoscopy unit (fictional)",
    "PROVINCIAL": "Provincial hospital (fictional)",
}
TIMES = (time(9, 0), time(10, 0), time(11, 0), time(14, 0))
DAYS_AHEAD = 14
CAPACITY = 2
SLOT_MINUTES = 30
LABEL = "Simulated slots: not a real clinic schedule"


def default_clinic(location: str | None, screening_type: str) -> str:
    if screening_type == "fit":
        return "DISTRICT"
    loc = (location or "").strip().upper().replace(" ", "-")
    return loc if loc in CLINICS else "SITE-A"


def slot_id(clinic: str, day: date, at: time) -> str:
    return f"{clinic}|{day.isoformat()}T{at.strftime('%H:%M')}"


def parse_slot(sid: str) -> tuple[str, date, time] | None:
    try:
        clinic, rest = sid.split("|", 1)
        d, t = rest.split("T", 1)
        return clinic, date.fromisoformat(d), time.fromisoformat(t)
    except ValueError:
        return None


def is_offered(sid: str, today: date) -> bool:
    """Rule APPT-1: only slots this simulated schedule actually offers (weekday, listed time, next 14 days)."""
    p = parse_slot(sid)
    if p is None:
        return False
    clinic, d, t = p
    return clinic in CLINICS and t in TIMES and d.weekday() < 5 and today < d <= today + timedelta(days=DAYS_AHEAD)


def slots(clinic: str, today: date, booked: dict[str, int], due: date | None) -> list[dict[str, Any]]:
    out = []
    for i in range(1, DAYS_AHEAD + 1):
        d = today + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        for t in TIMES:
            sid = slot_id(clinic, d, t)
            n = booked.get(sid, 0)
            out.append(
                {
                    "slot_id": sid,
                    "date": d.isoformat(),
                    "time": t.strftime("%H:%M"),
                    "free": max(CAPACITY - n, 0),
                    "capacity": CAPACITY,
                    "after_deadline": bool(due and d > due),
                }
            )
    return out


def appointment(sid: str, *, case_id: str, masked_participant: str, reason: str | None) -> dict[str, Any]:
    """The appointment stored on the case: date and clinic (as before) plus a FHIR R4 Appointment resource."""
    p = parse_slot(sid)
    assert p is not None
    clinic, d, t = p
    start = datetime.combine(d, t, tzinfo=MANILA)
    end = start + timedelta(minutes=SLOT_MINUTES)
    fhir = {
        "resourceType": "Appointment",
        "status": "booked",
        "description": reason or "Follow-up after a screening result",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "slot": [{"reference": f"Slot/{sid.replace('|', '-').replace(':', '')}", "display": "simulated slot"}],
        "participant": [
            {"actor": {"display": f"Patient {masked_participant} (LoopCloser case {case_id})"}, "status": "accepted"},
            {"actor": {"display": CLINICS[clinic]}, "status": "accepted"},
        ],
        "meta": {"tag": [{"system": "urn:loopcloser:data-label", "code": "SIMULATED"}]},
    }
    return {
        "date": d.isoformat(),
        "time": t.strftime("%H:%M"),
        "clinic": CLINICS[clinic],
        "clinic_id": clinic,
        "slot_id": sid,
        "status": "booked",
        "simulated": True,
        "fhir": fhir,
    }
