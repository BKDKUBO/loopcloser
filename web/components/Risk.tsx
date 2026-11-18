"use client";

import Link from "next/link";
import { KindBadge } from "@/components/Kind";
import { BARRIER_LABELS, label } from "@/lib/labels";
import type { AttendanceRisk, CaseView } from "@/lib/types";

const NOTE = "Rules the team chose, not a validated prediction. Administrative only: never changes the case or its priority, never contacts anyone.";

export function RiskBadge({ r }: { r?: AttendanceRisk | null }) {
  if (!r || r.level === "none") return null;
  return <span className={`badge risk-${r.level}`} title={NOTE}>Drop-off risk: {r.level === "high" ? "high" : "watch"}</span>;
}

function reasonText(x: AttendanceRisk["reasons"][number]) {
  if (x.rule_id === "RISK-BARRIER" && x.detail) return `Barrier: ${label(BARRIER_LABELS, x.detail)}`;
  return x.detail ? `${x.label} (${x.detail})` : x.label;
}

/** Case page: the drop-off signs, their points and an administrative suggestion for each. */
export function RiskPanel({ c }: { c: CaseView }) {
  const r = c.attendance_risk;
  if (!r || r.excluded) return null;
  return (
    <section aria-labelledby="risk-h"><h2 id="risk-h">Drop-off risk <KindBadge kind="rule" /> <RiskBadge r={r} /></h2>
      {r.reasons.length === 0 ? <p className="muted">No drop-off signs.</p> : (
        <ul>{r.reasons.map((x, i) => (
          <li key={i}><strong>{reasonText(x)}</strong> +{x.points} · <span className="muted small">{x.rule_id}</span>
            <div className="small">Suggested help: {x.help}</div></li>))}</ul>
      )}
      <p className="muted small">{r.points} points; watch at 3, high at 6. {NOTE}</p>
    </section>
  );
}

/** Today: open cases with the most drop-off signs, among the cases already loaded in the lanes below. */
export function AtRiskStrip({ cases }: { cases: CaseView[] }) {
  const seen = new Set<string>();
  const top = cases
    .filter((c) => c.attendance_risk && c.attendance_risk.level !== "none" && !seen.has(c.id) && seen.add(c.id))
    .sort((a, b) => (b.attendance_risk!.points - a.attendance_risk!.points) || a.id.localeCompare(b.id))
    .slice(0, 8);
  if (top.length === 0) return null;
  return (
    <section aria-labelledby="atrisk-h" className="card atrisk">
      <h2 id="atrisk-h">At risk of dropping off <KindBadge kind="rule" /></h2>
      <p className="muted small">From the highest-priority cases shown in the lanes below. {NOTE}</p>
      <ul className="atrisk-list">{top.map((c) => (
        <li key={c.id}><RiskBadge r={c.attendance_risk} /> <Link href={`/case?id=${encodeURIComponent(c.id)}`}>{c.id}</Link>{" "}
          <span className="small">{c.attendance_risk!.reasons.map((x) => reasonText(x)).join(" · ")}</span>
          {c.attendance_risk!.reasons[0] && <div className="muted small">Next: {c.attendance_risk!.reasons[0].help}</div>}</li>))}
      </ul>
    </section>
  );
}
