"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { LANE_LABELS, groupByLane, humanState, type Lane } from "@/lib/lanes";
import type { CaseView } from "@/lib/types";

function Today() {
  const s = useSession();
  const [cases, setCases] = useState<CaseView[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    s.headers().then((h) => api<{ cases: CaseView[] }>("/api/cases", h))
      .then((r) => setCases(r.cases)).catch((e: Error) => setErr(e.message));
  }, [s]);

  if (err) return <p className="error" role="alert">{err}</p>;
  if (!cases) return <p>Loading cases…</p>;
  const today = new Date().toISOString().slice(0, 10);
  const lanes = groupByLane(cases, today);

  return (
    <>
      <h1>Today</h1>
      <div className="lanes">
        {(Object.keys(LANE_LABELS) as Lane[]).map((lane) => (
          <section key={lane} aria-labelledby={`lane-${lane}`}>
            <h2 id={`lane-${lane}`}>{LANE_LABELS[lane]} ({lanes[lane].length})</h2>
            {lanes[lane].length === 0 && <p className="muted">No cases here.</p>}
            {lanes[lane].slice(0, 25).map((c) => (
              <article key={c.id} className="card">
                <div>
                  {c.clinical_urgency === "urgent" && <span className="badge urgent">Urgent</span>}
                  {c.red_flag_open && <span className="badge urgent">Red flag: automation paused</span>}
                  {c.synthetic && <span className="badge">SIMULATED</span>}
                </div>
                <strong><Link href={`/case?id=${encodeURIComponent(c.id)}`}>{c.participant_id}</Link></strong>
                {" · "}{c.screening_type.toUpperCase()} · {humanState(c.state)}
                <div className="muted">Due {c.due_date ?? "not set"} · Owner {c.owner ?? "none (needs owner)"}</div>
                <div>Next: {c.next_action}</div>
              </article>
            ))}
          </section>
        ))}
      </div>
    </>
  );
}

export default function Page() {
  return <RequireRole><Today /></RequireRole>;
}
