"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { CallPrep } from "@/components/CallPrep";
import { CaseActions } from "@/components/CaseActions";
import { PriorityBadge, WhyPriority } from "@/components/Priority";
import { RequireRole } from "@/components/RequireRole";
import { SafetyLine } from "@/components/SafetyLine";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { humanState } from "@/lib/lanes";
import { useCaseAction } from "@/lib/useCaseAction";
import type { CaseEvent, CaseView } from "@/lib/types";

const OVERRIDE_REASONS = ["duplicate", "already_treated", "worsening_symptoms", "completed_elsewhere", "data_error",
  "clinical_judgment_documented", "other"];
const BARRIERS = ["transport", "cost", "work", "language", "digital", "childcare", "fear"];

function NextActionPanel({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const s = useSession();
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState(c.due_date ?? "");
  const [clinic, setClinic] = useState("Site A clinic");
  const [evidence, setEvidence] = useState("");
  const ra = c.recommended_action;
  const isLead = s.role === "coordinator" || s.role === "supervisor";
  const t = (target: string, extra: Record<string, unknown> = {}, ok = "Done.") =>
    run(`/api/cases/${c.id}/transition`, { target, ...extra }, undefined, ok);

  return (
    <aside className="sticky" aria-labelledby="nap">
      <h2 id="nap">Next action</h2>
      <p><strong>{ra?.label}</strong></p>
      <p className="muted">Why: case is at &quot;{humanState(c.state)}&quot;, due {c.due_date ?? "not set"}.
        {c.next_action ? ` Pathway step: ${c.next_action}` : ""}</p>
      {c.state !== "closed" && (
        <>
          {ra?.kind === "transition" && ra.target && ra.target !== "action_scheduled" && (
            <button className="primary" disabled={busy}
              onClick={() => t(ra.target!, ra.target === "understanding_confirmed" ? { source: "staff_confirmed" } : {})}>
              Complete next action
            </button>
          )}
          {(ra?.target === "action_scheduled" || ["understanding_confirmed", "rescheduled", "no_show"].includes(c.state)) && (
            <fieldset><legend>Book appointment (simulated slots)</legend>
              <label>Date <input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>{" "}
              <label>Clinic <input value={clinic} onChange={(e) => setClinic(e.target.value)} /></label>{" "}
              <button className="primary" disabled={busy || !date}
                onClick={() => t("action_scheduled", { appointment: { date, clinic } }, "Appointment booked.")}>Book</button>
            </fieldset>
          )}
          {ra?.kind === "close" && isLead && (
            <fieldset><legend>Close case</legend>
              <label>Evidence (visit record or upload id) <input value={evidence} onChange={(e) => setEvidence(e.target.value)} /></label>
              <label>Reason <input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              <button disabled={busy || !reason || !evidence} onClick={() => run(`/api/cases/${c.id}/close`,
                { closure_reason: reason, evidence_ref: evidence }, undefined, "Closed.")}>Close with evidence</button>
            </fieldset>
          )}
          <div className="row">
            {c.state === "action_scheduled" && (
              <button disabled={busy || !reason} onClick={() => t("rescheduled", { reason }, "Marked for rescheduling.")}>Reschedule</button>
            )}
            <button disabled={busy || !reason} onClick={() => t("escalated", { reason }, "Escalated.")}>Escalate</button>
          </div>
          <label>Reason (needed to reschedule or escalate){" "}
            <input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
          <hr />
          <CaseActions c={c} onChange={onChange} />
        </>
      )}
      {notice && <p className="ok" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </aside>
  );
}

function OverrideForm({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [tier, setTier] = useState("high");
  const [reason, setReason] = useState("worsening_symptoms");
  const [note, setNote] = useState("");
  return (
    <fieldset><legend>Supervisor override (logged as an event)</legend>
      <div className="row">
        <label>Tier <select value={tier} onChange={(e) => setTier(e.target.value)}>
          {["urgent", "high", "moderate", "routine"].map((x) => <option key={x}>{x}</option>)}
          <option value="">clear override</option></select></label>
        <label>Reason <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {OVERRIDE_REASONS.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Note <input value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <button disabled={busy || !note.trim()} onClick={() => run(`/api/cases/${c.id}/priority-override`,
          { tier: tier || null, reason, note }, undefined, "Override saved.")}>Save override</button>
      </div>
      {notice && <p className="ok">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </fieldset>
  );
}

function Barriers({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const { run, busy, error } = useCaseAction(onChange);
  const [b, setB] = useState("transport");
  const [res, setRes] = useState("");
  return (
    <section aria-labelledby="bar"><h2 id="bar">Barriers</h2>
      {(c.barriers_open ?? []).length === 0 ? <p className="muted">No open barriers.</p> : (
        <ul>{c.barriers_open!.map((x) => (
          <li key={x}>{x}{" "}
            <input aria-label={`How was ${x} resolved`} placeholder="How it was resolved" value={res}
              onChange={(e) => setRes(e.target.value)} />{" "}
            <button disabled={busy || !res} onClick={() => run(`/api/cases/${c.id}/barriers`, { barrier: x, resolution: res })}>Resolve</button>
          </li>))}</ul>
      )}
      <div className="row">
        <select aria-label="Barrier type" value={b} onChange={(e) => setB(e.target.value)}>
          {BARRIERS.map((x) => <option key={x}>{x}</option>)}</select>
        <button disabled={busy} onClick={() => run(`/api/cases/${c.id}/barriers`, { barrier: b })}>Report barrier</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}

function CaseDetail() {
  const id = useSearchParams().get("id") ?? "";
  const s = useSession();
  const [c, setC] = useState<CaseView | null>(null);
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    const h = await s.headers();
    try {
      setC(await api<CaseView>(`/api/cases/${encodeURIComponent(id)}`, h));
      if (s.role !== "patient") setEvents(await api<CaseEvent[]>(`/api/cases/${encodeURIComponent(id)}/events`, h));
    } catch (e) { setErr((e as Error).message); }
  }, [id, s]);
  useEffect(() => { load(); }, [load]);
  const changed = () => { load(); };

  if (!id) return <p>No case selected.</p>;
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!c) return <p>Loading…</p>;
  return (
    <>
      <h1>Case {c.id} · {c.participant_id}</h1>
      <p>
        <PriorityBadge p={c.priority} />
        <span className={`badge ${c.clinical_urgency === "urgent" ? "urgent" : ""}`}>Clinical urgency: {c.clinical_urgency}</span>
        <span className="badge">Status: {humanState(c.state)}</span>
        <span className="badge">Deadline: {c.due_date ?? "not set"}</span>
        <span className="badge">Owner: {c.owner ?? "none"}</span>
        <span className="badge pending">Pathway {c.pathway_id} v{c.pathway_version}: pending clinical sign-off</span>
        {c.synthetic && <span className="badge">SIMULATED</span>}
      </p>
      {c.red_flag_open && <p className="error">Red flag open. Automation is paused until a human resolves it.</p>}
      {c.data_quality.length > 0 && <p className="error">Data quality: {c.data_quality.join(", ")}</p>}
      <div className="detail">
        <div>
          <section aria-labelledby="pri"><h2 id="pri">Follow-up priority</h2>
            <p>{c.priority?.explanation}</p>
            <WhyPriority p={c.priority} open />
            {s.role === "supervisor" && c.state !== "closed" && <OverrideForm c={c} onChange={changed} />}
          </section>
          <CallPrep caseId={c.id} onLogged={changed}
            disabledReason={c.state === "closed" ? "Case closed." : c.red_flag_open ? "Red flag open: a person handles this case, no AI drafts (rule AI-2)." : undefined} />
          <SafetyLine pathway={`${c.pathway_id} v${c.pathway_version}`} />
          <Barriers c={c} onChange={changed} />
          <section aria-labelledby="lad"><h2 id="lad">Escalation ladder (day {c.day ?? 0})</h2>
            <ol className="ladder">{(c.ladder ?? []).map((st) => (
              <li key={st.id} className={st.state.replace(" ", "-")}>Day {st.day}: {st.label} · {st.state}</li>))}</ol>
          </section>
          <section aria-labelledby="tl"><h2 id="tl">Timeline (event log)</h2>
            {events.length === 0 ? <p className="muted">No events visible for your role.</p> : (
              <ol>{events.map((e) => (
                <li key={e.id}><strong>{e.type.replace(/_/g, " ")}</strong>
                  {typeof e.payload.to === "string" && <> to {humanState(e.payload.to)}</>}
                  {typeof e.payload.template_id === "string" && <> ({String(e.payload.template_id)}, {String(e.payload.language)})</>}
                  {typeof e.payload.step === "string" && <> Day {String(e.payload.day)}: {String(e.payload.action)}</>}
                  {" "}<span className="muted">by {e.actor.id} ({e.actor.role}{e.actor.kind !== "human" ? `, ${e.actor.kind}` : ""})
                    {" "}at {new Date(e.at).toLocaleString()}{e.rule_id && <> · rule {e.rule_id}</>}</span>
                </li>))}</ol>
            )}
          </section>
        </div>
        <NextActionPanel c={c} onChange={changed} />
      </div>
    </>
  );
}

export default function Page() {
  return <RequireRole><Suspense fallback={<p>Loading…</p>}><CaseDetail /></Suspense></RequireRole>;
}
