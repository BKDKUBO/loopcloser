"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { CallPrep } from "@/components/CallPrep";
import { CaseActions } from "@/components/CaseActions";
import { ConfirmButton } from "@/components/ConfirmButton";
import { Downloads } from "@/components/Downloads";
import { Gates } from "@/components/Gates";
import { KindBadge, KindLegend } from "@/components/Kind";
import { PriorityBadge, WhyPriority } from "@/components/Priority";
import { RequireRole } from "@/components/RequireRole";
import { RevealContact } from "@/components/RevealContact";
import { SafetyLine } from "@/components/SafetyLine";
import { SlotPicker } from "@/components/SlotPicker";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import {
  BARRIER_LABELS, OVERRIDE_REASON_LABELS, SCREENING_LABELS, STATE_LABELS, actorLabel, dueText, label, ownerLabel,
} from "@/lib/labels";
import { eventKind } from "@/lib/kinds";
import { describeEvent } from "@/lib/timeline";
import { useCaseAction } from "@/lib/useCaseAction";
import { liveText, useAutoRefresh } from "@/lib/useAutoRefresh";
import type { CaseEvent, CaseView } from "@/lib/types";

const OVERRIDE_REASONS = Object.keys(OVERRIDE_REASON_LABELS);
const BARRIERS = Object.keys(BARRIER_LABELS);

/** Closing needs evidence AND a supervisor's sign-off (rules CLOSE-1, CLOSE-2, CLOSE-3). After a visit the evidence is
 * the visit record; for a declined or unreachable case it is a documented reference. Coordinators see the same
 * checklist, so they can prepare the evidence, but only a supervisor can sign off. */
function CloseWithEvidence({ c, run, busy }: { c: CaseView; run: ReturnType<typeof useCaseAction>["run"]; busy: boolean }) {
  const s = useSession();
  const structured = c.state === "visit_completed";
  const [visit, setVisit] = useState(c.appointment?.date ?? "");
  const [facility, setFacility] = useState(c.appointment?.clinic ?? "");
  const [record, setRecord] = useState("");
  const [ref, setRef] = useState("");
  const [reason, setReason] = useState(structured ? "Visit completed" : "");
  const [signed, setSigned] = useState(false);
  const isSup = s.role === "supervisor";
  const missing = [
    ...(structured
      ? [!visit && "visit date", !facility.trim() && "facility", !record.trim() && "record number"]
      : [ref.trim().length < 5 && "evidence reference (what was documented, where)"]),
    !reason.trim() && "reason",
    !isSup && "a supervisor's sign-off (switch to Supervisor)",
    isSup && !signed && "your sign-off (tick the box)",
  ].filter(Boolean) as string[];
  const body = structured
    ? { closure_reason: reason, evidence: { visit_date: visit, facility, record_number: record }, sign_off: signed }
    : { closure_reason: reason, evidence_ref: ref, sign_off: signed };
  return (
    <fieldset><legend>Close: evidence + supervisor sign-off</legend>
      {structured ? (
        <>
          <label>Visit date <input type="date" value={visit} onChange={(e) => setVisit(e.target.value)} required /></label>
          <label>Facility <input value={facility} onChange={(e) => setFacility(e.target.value)} maxLength={120} required /></label>
          <label>Record number <input value={record} onChange={(e) => setRecord(e.target.value)} maxLength={40} required
            placeholder="e.g. RHU-A 2211" /></label>
        </>
      ) : (
        <label>Evidence (what was documented, where) <input value={ref} onChange={(e) => setRef(e.target.value)} maxLength={300}
          placeholder="e.g. Decline recorded on the 12 Nov call after counselling" /></label>
      )}
      <label>Reason {structured ? "" : "(what the patient decided, what they were told) "}
        <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>
      {isSup && (
        <label><input type="checkbox" checked={signed} onChange={(e) => setSigned(e.target.checked)} /> I reviewed the
          evidence and sign off this closure (my name is recorded)</label>
      )}
      {missing.length > 0 && <p className="muted">Needed before closing: {missing.join(", ")} (rules CLOSE-1, CLOSE-2).</p>}
      <ConfirmButton disabled={busy || missing.length > 0} confirm="Sign off and close this case? Closing cannot be undone."
        onConfirm={() => run(`/api/cases/${c.id}/close`, body, undefined, "Closed with evidence and your sign-off.")}>
        Sign off and close
      </ConfirmButton>
    </fieldset>
  );
}

function NextActionPanel({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const s = useSession();
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [reason, setReason] = useState("");
  const ra = c.recommended_action;
  const isLead = s.role === "coordinator" || s.role === "supervisor";
  const t = (target: string, extra: Record<string, unknown> = {}, ok = "Done.") =>
    run(`/api/cases/${c.id}/transition`, { target, ...extra }, undefined, ok);
  const oneClick = ra?.kind === "transition" && ra.target && ra.target !== "action_scheduled";
  const callPrepBlocked = c.red_flag_open ? "Red flag open: a person handles this case, no AI drafts (rule AI-2)." : undefined;

  return (
    <aside className="sticky" aria-labelledby="nap">
      <h2 id="nap">Next action <KindBadge kind="rule" /></h2>
      <p><strong>{ra?.label}</strong></p>
      <p className="muted">Why: the case is at &quot;{label(STATE_LABELS, c.state)}&quot;
        {c.plain_status === "done" ? "." : ` and is ${dueText(c.days_to_due).toLowerCase()}.`}
        {c.next_action ? ` Pathway step: ${c.next_action}` : ""}</p>
      {c.state !== "closed" && (
        <>
          {oneClick && (
            <ConfirmButton primary disabled={busy} confirm={`Mark as "${label(STATE_LABELS, ra!.target)}"?`}
              onConfirm={() => t(ra!.target!, ra!.target === "understanding_confirmed" ? { source: "staff_confirmed" } : {},
                `Done: ${label(STATE_LABELS, ra!.target)}.`)}>
              Complete: {label(STATE_LABELS, ra!.target)}
            </ConfirmButton>
          )}
          {(ra?.target === "action_scheduled" || ["understanding_confirmed", "rescheduled", "no_show"].includes(c.state)) && (
            <SlotPicker c={c} run={run} busy={busy} />
          )}
          {ra?.kind === "close" && isLead && <CloseWithEvidence c={c} run={run} busy={busy} />}
          {ra?.kind === "consent" && <p className="pending">On hold until consent to contact is recorded. Use
            &quot;Checks before contact&quot; on the left. A home visit is still allowed.</p>}
          {ra?.kind === "close" && !isLead && <p className="muted">Closing needs evidence and a supervisor&apos;s sign-off (rules CLOSE-1, CLOSE-2).</p>}
          <hr />
          <CaseActions c={c} onChange={onChange} showRecommended={false}
            extra={<CallPrep caseId={c.id} onLogged={() => onChange(c)} disabledReason={callPrepBlocked} />} />
          <details>
            <summary>Reschedule or escalate</summary>
            <label>Reason (needed){" "}<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
            <div className="row">
              {c.state === "action_scheduled" && (
                <ConfirmButton disabled={busy || !reason} confirm="Mark for rescheduling?"
                  onConfirm={() => t("rescheduled", { reason }, "Marked for rescheduling.")}>Reschedule</ConfirmButton>
              )}
              <ConfirmButton disabled={busy || !reason} confirm="Escalate to the supervisor?"
                onConfirm={() => t("escalated", { reason }, "Escalated.")}>Escalate</ConfirmButton>
            </div>
          </details>
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
    <details><summary>Supervisor override (logged as an event)</summary>
      <div className="row">
        <label>Tier <select value={tier} onChange={(e) => setTier(e.target.value)}>
          {["urgent", "high", "moderate", "routine"].map((x) => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
          <option value="">Clear override</option></select></label>
        <label>Reason <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {OVERRIDE_REASONS.map((x) => <option key={x} value={x}>{OVERRIDE_REASON_LABELS[x]}</option>)}</select></label>
        <label>Note <input value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <ConfirmButton disabled={busy || !note.trim()} confirm="Save this override?" onConfirm={() => run(`/api/cases/${c.id}/priority-override`,
          { tier: tier || null, reason, note }, undefined, "Override saved.")}>Save override</ConfirmButton>
      </div>
      {notice && <p className="ok">{notice}</p>}{error && <p className="error" role="alert">{error}</p>}
    </details>
  );
}

/** One open barrier, with its own resolution text and result (each barrier keeps its own state). */
function BarrierItem({ c, barrier, onChange }: { c: CaseView; barrier: string; onChange: (c: CaseView) => void }) {
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [res, setRes] = useState("");
  return (
    <li>{label(BARRIER_LABELS, barrier)}{" "}
      <input aria-label={`How was ${label(BARRIER_LABELS, barrier)} resolved`} placeholder="How it was resolved" value={res}
        onChange={(e) => setRes(e.target.value)} />{" "}
      <button disabled={busy || !res.trim()} onClick={() => run(`/api/cases/${c.id}/barriers`, { barrier, resolution: res },
        undefined, "Resolved.")}>Resolve</button>
      {notice && <span className="ok" role="status"> {notice}</span>}
      {error && <span className="error" role="alert"> {error}</span>}
    </li>
  );
}

function Barriers({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const { run, busy, error } = useCaseAction(onChange);
  const [b, setB] = useState("transport");
  return (
    <section aria-labelledby="bar"><h2 id="bar">Barriers <KindBadge kind="fact" /></h2>
      {(c.barriers_open ?? []).length === 0 ? <p className="muted">No open barriers.</p> : (
        <ul>{c.barriers_open!.map((x) => <BarrierItem key={x} c={c} barrier={x} onChange={onChange} />)}</ul>
      )}
      {c.state !== "closed" && (
        <div className="row">
          <select aria-label="Barrier type" value={b} onChange={(e) => setB(e.target.value)}>
            {BARRIERS.map((x) => <option key={x} value={x}>{BARRIER_LABELS[x]}</option>)}</select>
          <button disabled={busy} onClick={() => run(`/api/cases/${c.id}/barriers`, { barrier: b })}>Report barrier</button>
        </div>
      )}
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

  const load = useCallback(async (silent = false) => {
    if (!id) return;
    const h = await s.headers();
    try {
      setC(await api<CaseView>(`/api/cases/${encodeURIComponent(id)}`, h));
      if (s.role !== "patient") setEvents(await api<CaseEvent[]>(`/api/cases/${encodeURIComponent(id)}/events`, h));
    } catch (e) { if (!silent) setErr((e as Error).message); }
  }, [id, s]);
  useEffect(() => { load(); }, [load]);
  const live = useAutoRefresh(() => load(true), Boolean(id));
  const changed = () => { load(); };

  if (!id) return <p>No case selected.</p>;
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!c) return <p>Loading…</p>;
  const closed = c.state === "closed";
  const overdue = (c.days_to_due ?? 0) < 0 && !closed && c.plain_status !== "done";
  const ev = c.closure_evidence_detail;
  const holds = c.gates_on_hold ?? [];
  const callHold = c.contact_consent === "no" ? "the patient declined contact"
    : holds.includes("consent") ? "consent to contact not recorded"
    : holds.includes("contact_details") ? "no valid phone number" : null;
  const src = c.source;
  return (
    <>
      <h1>Case {c.id} <span className="muted">· {c.participant_id}</span></h1>
      <p className={`live ${live.visible ? "" : "paused"}`}>{liveText(live.visible, live.checkedAt)}</p>
      <p><RevealContact caseId={c.id} synthetic={c.synthetic} onLogged={changed} callHold={callHold} /></p>
      <KindLegend />
      <p>
        <KindBadge kind="rule" />
        <PriorityBadge p={c.priority} />
        {c.clinical_urgency === "urgent" && <span className="badge urgent">Clinically urgent</span>}
        <span className={`status status-${c.plain_status}`}>{c.plain_status_label}</span>
        <span className={`badge ${overdue ? "urgent" : ""}`}>{c.plain_status === "done" ? (closed ? "Closed" : "Visit done") : dueText(c.days_to_due)}</span>
        {c.lost_contact && <span className="badge urgent">Lost contact</span>}
      </p>
      <p>
        <KindBadge kind="fact" />
        <span className="badge">Owner: {ownerLabel(c.owner)}</span>
        <span className="badge">Consent to contact: {c.contact_consent === "yes" ? "yes" : c.contact_consent === "no" ? "declined" : "not recorded"}</span>
        <span className="badge">Phone: {c.phone_valid === false ? "none valid" : "on file"}</span>
        {c.sms_opt_out && <span className="badge urgent" title="Rule MSG-4">SMS: patient replied STOP</span>}
        {c.last_sms_reply && !c.sms_opt_out && <span className="badge">Last SMS reply: {c.last_sms_reply.keyword} (simulated)</span>}
        {c.appointment?.confirmed_by_patient && c.state === "action_scheduled" && <span className="badge">Appointment confirmed by the patient (SMS YES)</span>}
      </p>
      {c.appointment && ["action_scheduled", "rescheduled", "no_show", "visit_completed"].includes(c.state) && (
        <p className="small"><KindBadge kind="fact" />{" "}
          <strong>{c.state === "action_scheduled" ? "Appointment" : "Last appointment"}:</strong> {c.appointment.date}
          {c.appointment.time ? ` ${c.appointment.time}` : ""} at {c.appointment.clinic}
          {c.appointment.slot_id ? " (simulated slot)" : ""}
          {c.appointment.fhir && (
            <details><summary>FHIR R4 Appointment (stored on the case, not sent)</summary>
              <pre className="small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(c.appointment.fhir, null, 2)}</pre></details>)}
        </p>
      )}
      {src?.kind === "fhir_r4_bundle" && (
        <p className="small"><KindBadge kind="fact" /> <strong>Received as a FHIR R4 Bundle</strong> (pasted or sample, no live EHR):{" "}
          <code>{src.resource}</code>{src.code ? <> · {src.code}{src.display ? ` (${src.display})` : ""}</> : null}
          {src.interpretation ? <> · lab interpretation {src.interpretation}</> : null}
          {src.referral ? <> · referral in the bundle: {src.referral}</> : null}</p>
      )}
      <p className="muted">{label(SCREENING_LABELS, c.screening_type)} · status in detail: {label(STATE_LABELS, c.state)} ·
        {" "}<span className="pending">pathway {c.pathway_id} v{c.pathway_version}, pending clinical sign-off</span> · {c.synthetic ? "fictional (SIMULATED) case" : "not tagged synthetic"} ·
        {" "}<Link href={`/phone?id=${encodeURIComponent(c.id)}`}>See the patient&apos;s phone (simulated SMS)</Link></p>
      {c.red_flag_open && <p className="error">Red flag open. Automation is paused until a person resolves it.</p>}
      {c.data_quality.includes("no_owner") && !closed && <p className="error">Nobody owns this case yet. Assign an owner.</p>}
      {closed && (
        <p className="ok"><KindBadge kind="fact" /> Closed: {c.closure_reason}.{" "}
          {ev ? <>Evidence: visit {ev.visit_date} at {ev.facility}, record {ev.record_number}.</> : c.closure_evidence ? <>Evidence: {c.closure_evidence}.</> : null}
          {c.signed_off_by && <> Signed off by {c.signed_off_by}.</>}</p>
      )}
      <div className="detail">
        <div>
          <Gates c={c} onChange={changed} />
          <section aria-labelledby="pri"><h2 id="pri">Follow-up priority <KindBadge kind="rule" /></h2>
            <p>{c.priority?.explanation}</p>
            <WhyPriority p={c.priority} open />
            {s.role === "supervisor" && !closed && <OverrideForm c={c} onChange={changed} />}
          </section>
          <SafetyLine pathway={`${c.pathway_id} v${c.pathway_version}`} collapsed />
          <Barriers c={c} onChange={changed} />
          <section aria-labelledby="lad"><h2 id="lad">Escalation ladder (day {c.day ?? 0}) <KindBadge kind="rule" /></h2>
            <ol className="ladder">{(c.ladder ?? []).map((st) => (
              <li key={st.id} className={st.state.replace(" ", "-")}>Day {st.day}: {st.label} · {st.state}</li>))}</ol>
          </section>
          <section aria-labelledby="tl"><h2 id="tl">Timeline (full event log)</h2>
            {events.length === 0 ? <p className="muted">No events visible for your role.</p> : (
              <ol className="timeline">{events.map((e) => (
                <li key={e.id}><KindBadge kind={eventKind(e)} /> {describeEvent(e)}
                  <div className="muted small">{actorLabel(e.actor)} · {new Date(e.at).toLocaleString()}
                    {e.rule_id && <> · rule {e.rule_id}</>} · <code>{e.type}</code></div>
                </li>))}</ol>
            )}
          </section>
          <Downloads caseId={c.id} onLogged={changed} />
        </div>
        <NextActionPanel c={c} onChange={changed} />
      </div>
    </>
  );
}

export default function Page() {
  return <RequireRole><Suspense fallback={<p>Loading…</p>}><CaseDetail /></Suspense></RequireRole>;
}
