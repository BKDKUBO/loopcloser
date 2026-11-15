"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { KindBadge, KindLegend } from "@/components/Kind";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { kindFromApi } from "@/lib/kinds";
import { actorLabel, label, STATE_LABELS, words } from "@/lib/labels";
import { describeEvent } from "@/lib/timeline";
import type { CaseEvent, Gate, LadderStep, Priority, RecommendedAction } from "@/lib/types";

interface Summary {
  case_id: string;
  generated_at: string;
  generated_by: string;
  data_label: string | null;
  recorded_facts: Record<string, unknown>;
  rule_results: {
    state: string; plain_status: string; pathway: string; due_date: string | null; days_to_due: number | null;
    priority: Priority; recommended_action: RecommendedAction; gates: Gate[]; ladder: LadderStep[];
  };
  ai_written: { label: string; model: string | null; verified: boolean; text: string | null; decision: string | null; decided_by: string | null } | null;
  timeline: (CaseEvent & { content_kind: string; actor_id: string; actor_role: string; actor_kind: string })[];
}

const show = (v: unknown): string => {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "none";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${words(k).toLowerCase()} ${show(x)}`).join(", ");
  return String(v);
};

/** Printable case summary (browser Print or Save as PDF). Staff only; the download is logged (PRIV-2). */
function PrintSummary() {
  const id = useSearchParams().get("id") ?? "";
  const s = useSession();
  const [d, setD] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fetched = useRef<string | null>(null); // each load is a logged download: fetch once per case
  useEffect(() => {
    if (!id || !s.role || fetched.current === id) return;
    fetched.current = id;
    (async () => {
      try { setD(await api<Summary>(`/api/cases/${encodeURIComponent(id)}/export/summary`, await s.headers())); }
      catch (e) { setErr((e as Error).message); }
    })();
  }, [id, s]);
  if (!id) return <p>No case selected.</p>;
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!d) return <p>Loading…</p>;
  const r = d.rule_results;
  return (
    <article className="print">
      <p className="noprint row">
        <button className="primary" onClick={() => window.print()}>Print or save as PDF</button>
        <Link href={`/case?id=${encodeURIComponent(d.case_id)}`}>Back to the case</Link>
      </p>
      <h1>Case summary {d.case_id}</h1>
      <p className="muted small">Generated {new Date(d.generated_at).toLocaleString()} by {d.generated_by}.
        {d.data_label && <> <strong>{d.data_label}</strong>: fictional case, not clinical evidence.</>} Pathway rules are
        pending clinical sign-off. Names and phone numbers are never included.</p>
      <KindLegend />

      <h2>Recorded facts <KindBadge kind="fact" /></h2>
      <table className="facts"><tbody>{Object.entries(d.recorded_facts).map(([k, v]) => (
        <tr key={k}><th>{words(k)}</th><td>{show(v)}</td></tr>))}</tbody></table>

      <h2>Rule results <KindBadge kind="rule" /></h2>
      <table className="facts"><tbody>
        <tr><th>Status</th><td>{r.plain_status} ({label(STATE_LABELS, r.state)})</td></tr>
        <tr><th>Pathway</th><td>{r.pathway}</td></tr>
        <tr><th>Deadline</th><td>{r.due_date ?? "—"}{r.days_to_due !== null && ` (${r.days_to_due < 0 ? `${-r.days_to_due} days overdue` : `in ${r.days_to_due} days`})`}</td></tr>
        <tr><th>Follow-up priority</th><td>{r.priority.explanation}</td></tr>
        <tr><th>Next action</th><td>{r.recommended_action.label}</td></tr>
        <tr><th>Checks before contact</th><td><ul>{r.gates.map((g) => (
          <li key={g.id}>{g.status === "pass" ? "Pass" : "HOLD"}: {g.label}. {g.detail}{g.missing ? `. Missing: ${g.missing}` : ""}</li>))}</ul></td></tr>
        <tr><th>Escalation ladder</th><td><ul>{r.ladder.map((st) => <li key={st.id}>Day {st.day}: {st.label} · {st.state}</li>)}</ul></td></tr>
      </tbody></table>

      <h2>AI-written <KindBadge kind="ai" /></h2>
      {d.ai_written ? (
        <div>
          <p className="small">{d.ai_written.label} ({d.ai_written.model ?? "offline template"}). {d.ai_written.decision
            ? `${d.ai_written.decision === "use" ? "Used" : "Discarded"} by ${d.ai_written.decided_by}.` : "No decision yet."}</p>
          {d.ai_written.verified ? <pre className="draft">{d.ai_written.text}</pre>
            : <p>Draft withheld: it mentioned facts not in the case record.</p>}
        </div>
      ) : <p className="muted">No AI draft on this case.</p>}

      <h2>Audit trail ({d.timeline.length} events)</h2>
      <table className="small audit">
        <thead><tr><th>#</th><th>When</th><th>Who</th><th>What</th><th>Kind</th><th>Rule</th></tr></thead>
        <tbody>{d.timeline.map((e) => (
          <tr key={e.seq}>
            <td>{e.seq}</td><td>{new Date(e.at).toLocaleString()}</td>
            <td>{actorLabel({ id: e.actor_id, role: e.actor_role, kind: e.actor_kind })}</td>
            <td>{describeEvent({ ...e, actor: { id: e.actor_id, role: e.actor_role, kind: e.actor_kind } })}</td>
            <td><KindBadge kind={kindFromApi(e.content_kind)} /></td><td>{e.rule_id || "—"}</td>
          </tr>))}</tbody>
      </table>
    </article>
  );
}

export default function Page() {
  return <RequireRole><Suspense fallback={<p>Loading…</p>}><PrintSummary /></Suspense></RequireRole>;
}
