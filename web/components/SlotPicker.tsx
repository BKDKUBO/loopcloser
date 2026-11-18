"use client";

import { useEffect, useState } from "react";
import { ConfirmButton } from "@/components/ConfirmButton";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import type { useCaseAction } from "@/lib/useCaseAction";
import type { CaseView } from "@/lib/types";

interface Slot { slot_id: string; date: string; time: string; free: number; capacity: number; after_deadline: boolean }
interface Slots { label: string; clinic: string; clinics: { id: string; name: string }[]; due_date: string | null; slots: Slot[] }

function dayLabel(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

/** Pick a simulated slot (rules APPT-1, APPT-2). The booking is stored as a FHIR R4 Appointment on the case. */
export function SlotPicker({ c, run, busy }: { c: CaseView; run: ReturnType<typeof useCaseAction>["run"]; busy: boolean }) {
  const s = useSession();
  const [clinic, setClinic] = useState<string>("");
  const [data, setData] = useState<Slots | null>(null);
  const [pick, setPick] = useState<Slot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [days, setDays] = useState(5);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const q = clinic ? `?clinic=${encodeURIComponent(clinic)}` : "";
        const r = await api<Slots>(`/api/cases/${encodeURIComponent(c.id)}/slots${q}`, await s.headers());
        if (live) { setData(r); setErr(null); if (!clinic) setClinic(r.clinic); }
      } catch (e) { if (live) setErr((e as Error).message); }
    })();
    return () => { live = false; };
  }, [c.id, c.version, clinic, s]);

  const byDay = new Map<string, Slot[]>();
  for (const x of data?.slots ?? []) byDay.set(x.date, [...(byDay.get(x.date) ?? []), x]);
  const dayList = Array.from(byDay.keys()).slice(0, days);
  const clinicName = data?.clinics.find((x) => x.id === clinic)?.name ?? clinic;
  return (
    <fieldset><legend>Book appointment</legend>
      <p className="pending small">{data?.label ?? "Simulated slots"}. Two places per slot; full slots are counted from bookings in
        LoopCloser only. The booking is saved on the case as a FHIR R4 Appointment (not sent anywhere).</p>
      {err && <p className="error" role="alert">{err}</p>}
      {data && (
        <>
          <label>Clinic <select value={clinic} onChange={(e) => { setClinic(e.target.value); setPick(null); }}>
            {data.clinics.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <div className="slots">
            {dayList.map((d) => (
              <div key={d} className="slot-day"><div className="small"><strong>{dayLabel(d)}</strong></div>
                {byDay.get(d)!.map((x) => (
                  <button key={x.slot_id} type="button" disabled={busy || x.free === 0}
                    className={`slot ${pick?.slot_id === x.slot_id ? "picked" : ""} ${x.after_deadline ? "late" : ""}`}
                    aria-pressed={pick?.slot_id === x.slot_id} onClick={() => setPick(x)}
                    title={x.after_deadline ? "After the pathway deadline" : undefined}>
                    {x.time} · {x.free === 0 ? "full" : `${x.free} free`}
                  </button>))}
              </div>))}
          </div>
          {byDay.size > days && <button type="button" onClick={() => setDays(days + 5)}>Later dates</button>}
          {pick?.after_deadline && <p className="pending small">This date is after the pathway deadline ({data.due_date}). Booking is
            allowed and the note is logged (rule APPT-1).</p>}
          <ConfirmButton primary disabled={busy || !pick} confirm={pick ? `Book ${dayLabel(pick.date)} ${pick.time} at ${clinicName}?` : ""}
            onConfirm={() => run(`/api/cases/${c.id}/appointments`, { slot_id: pick!.slot_id }, undefined,
              `Booked ${pick!.date} ${pick!.time} at ${clinicName} (simulated slot).`)}>
            {pick ? `Book ${pick.date} ${pick.time}` : "Pick a time"}
          </ConfirmButton>
        </>
      )}
    </fieldset>
  );
}
