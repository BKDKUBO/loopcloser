"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { SCREENING_LABELS, label } from "@/lib/labels";

interface Dash {
  today: string; total_cases: number; closed: number; closure_rate: number | null; closed_with_evidence: number;
  closed_with_signoff: number; median_days_to_care: number | null; days_to_care_n: number; open: number;
  overdue: number; lost_to_follow_up: number; unowned_open: number; red_flags_open: number; escalated_open: number;
  by_status: Record<string, number>; by_screening_type: Record<string, { total: number; closed: number; overdue: number }>;
  synthetic_share: number | null; definitions: Record<string, string>;
}

const pct = (x: number | null) => (x === null ? "n/a" : `${(x * 100).toFixed(1)}%`);

function Dashboard() {
  const s = useSession();
  const [d, setD] = useState<Dash | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { s.headers().then((h) => api<Dash>("/api/dashboard", h)).then(setD).catch((e: Error) => setErr(e.message)); }, [s]);
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!d) return <p>Loading…</p>;
  const tiles: [string, string, string][] = [
    ["Closure rate", pct(d.closure_rate), `${d.closed} of ${d.total_cases} cases closed (${d.closed_with_evidence} with visit evidence, ${d.closed_with_signoff} with a sign-off)`],
    ["Median days to care", d.median_days_to_care === null ? "n/a" : `${d.median_days_to_care}`, `from upload to recorded visit, over ${d.days_to_care_n} case${d.days_to_care_n === 1 ? "" : "s"}`],
    ["Overdue", `${d.overdue}`, `of ${d.open} open cases`],
    ["Lost to follow-up", `${d.lost_to_follow_up}`, "unable to reach, or 3+ failed contacts and none reached"],
    ["No owner", `${d.unowned_open}`, "open cases nobody owns"],
    ["Escalated / red flags", `${d.escalated_open} / ${d.red_flags_open}`, "waiting for a supervisor / a human red-flag review"],
  ];
  return (
    <>
      <h1>Program dashboard <span className="muted">({d.today})</span></h1>
      {d.synthetic_share !== null && d.synthetic_share > 0 && (
        <p className="notice" role="note">{pct(d.synthetic_share)} of these cases are fictional (SIMULATED). These numbers describe the
          demo data and the demo clock, not real patients or real outcomes.</p>
      )}
      <div className="tiles">
        {tiles.map(([t, v, sub]) => (
          <div key={t} className="card tile"><div className="muted">{t}</div><div className="big">{v}</div><div className="muted small">{sub}</div></div>
        ))}
      </div>
      <h2>By status</h2>
      <table><thead><tr><th>Status</th><th>Cases</th></tr></thead>
        <tbody>{Object.entries(d.by_status).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table>
      <h2>By screening type</h2>
      <table><thead><tr><th>Screening</th><th>Cases</th><th>Closed</th><th>Overdue</th></tr></thead>
        <tbody>{Object.entries(d.by_screening_type).map(([k, v]) => (
          <tr key={k}><td>{label(SCREENING_LABELS, k)}</td><td>{v.total}</td><td>{v.closed}</td><td>{v.overdue}</td></tr>))}</tbody></table>
      <h2>How each number is computed</h2>
      <ul>{Object.entries(d.definitions).map(([k, v]) => <li key={k}><strong>{k.replace(/_/g, " ")}</strong>: {v}</li>)}</ul>
      <p className="muted">Computed by the API from the case records, which are rebuilt from the append-only event log; days to care
        read the log directly. No AI and no estimates.</p>
    </>
  );
}

export default function Page() {
  return <RequireRole><Dashboard /></RequireRole>;
}
