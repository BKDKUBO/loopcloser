"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CaseActions } from "@/components/CaseActions";
import { PriorityBadge, WhyPriority } from "@/components/Priority";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { LANE_LABELS, humanState, type Lane } from "@/lib/lanes";
import type { CaseView } from "@/lib/types";

interface LaneBody { count: number; cases: CaseView[] }
interface TodayResponse { total: number; today: string; tier_counts: Record<string, number>; lanes: Record<Lane, LaneBody> }
const PER_LANE = 15;

function Today() {
  const s = useSession();
  const [data, setData] = useState<TodayResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setData(await api<TodayResponse>(`/api/today?per_lane=${PER_LANE}`, await s.headers())); }
    catch (e) { setErr((e as Error).message); }
  }, [s]);
  useEffect(() => { load(); }, [load]);

  const replace = (c: CaseView) =>
    setData((d) => d && {
      ...d,
      lanes: Object.fromEntries(Object.entries(d.lanes).map(([k, v]) =>
        [k, { ...v, cases: v.cases.map((x) => (x.id === c.id ? c : x)) }])) as Record<Lane, LaneBody>,
    });

  async function more(lane: Lane) {
    if (!data) return;
    const n = Math.min(data.lanes[lane].cases.length + 25, 200);
    const r = await api<{ cases: CaseView[] }>(`/api/cases?lane=${lane}&limit=${n}`, await s.headers());
    setData((d) => d && { ...d, lanes: { ...d.lanes, [lane]: { ...d.lanes[lane], cases: r.cases } } });
  }

  async function admin(path: string, body: unknown, label: string) {
    setBusy(true);
    setMsg(`${label}: working…`);
    try {
      const r = await api<Record<string, unknown>>(path, await s.headers(), { method: "POST", body: JSON.stringify(body) });
      const l = r.ladder as Record<string, number> | undefined;
      setMsg(l ? `${label}. Today is ${r.today}. Ladder: ${l.steps_run} steps on ${l.cases_touched} cases, ${l.reindexed} priorities refreshed, ${l.seconds}s.`
        : `${label}: ${JSON.stringify(r)}`);
      await load();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }

  if (err) return <p className="error" role="alert">{err}</p>;
  if (!data) return <p>Loading cases…</p>;

  return (
    <>
      <h1>Today <span className="muted">({data.today})</span></h1>
      <p>
        {(["urgent", "high", "moderate", "routine"] as const).map((t) => (
          <span key={t} className={`badge tier-${t}`}>{t[0].toUpperCase() + t.slice(1)}: {data.tier_counts[t] ?? 0}</span>
        ))}
        <span className="muted"> · {data.total} cases you can see</span>
      </p>
      {s.role === "supervisor" && s.demoMode && (
        <div className="card demo row" aria-label="Demo controls">
          <strong>Demo controls:</strong>
          {data.total === 0 && <button disabled={busy} onClick={() => admin("/api/demo/seed", { n: 1000 }, "Seeded")}>Load 1,000 SIMULATED patients</button>}
          <button disabled={busy} onClick={() => admin("/api/demo/clock", { advance_days: 1 }, "Advanced 1 day")}>Advance 1 day</button>
          <button disabled={busy} onClick={() => admin("/api/demo/clock", { advance_days: 3 }, "Advanced 3 days")}>Advance 3 days</button>
          <span className="muted">Advancing the clock runs the escalation ladder (Day 1, 2, 4, 7, 10, 14).</span>
        </div>
      )}
      {msg && <p className="muted" role="status">{msg}</p>}
      <div className="lanes">
        {(Object.keys(LANE_LABELS) as Lane[]).map((lane) => (
          <section key={lane} aria-labelledby={`lane-${lane}`}>
            <h2 id={`lane-${lane}`}>{LANE_LABELS[lane]} ({data.lanes[lane].count})</h2>
            {data.lanes[lane].count === 0 && <p className="muted">No cases here.</p>}
            {data.lanes[lane].cases.map((c) => (
              <article key={c.id} className="card" aria-label={`Case ${c.participant_id}`}>
                <div>
                  <PriorityBadge p={c.priority} />
                  {c.clinical_urgency === "urgent" && <span className="badge urgent">Clinical urgency: urgent</span>}
                  {c.red_flag_open && <span className="badge urgent">Red flag: automation paused</span>}
                  {c.synthetic && <span className="badge">SIMULATED</span>}
                </div>
                <strong><Link href={`/case?id=${encodeURIComponent(c.id)}`}>{c.participant_id}</Link></strong>
                {" · "}{c.screening_type.toUpperCase()} · {humanState(c.state)}
                <div className="muted">Due {c.due_date ?? "not set"} · Owner {c.owner ?? "none (needs owner)"}</div>
                <WhyPriority p={c.priority} />
                <CaseActions c={c} onChange={replace} compact />
              </article>
            ))}
            {data.lanes[lane].count > data.lanes[lane].cases.length && (
              <p className="muted">
                Showing the {data.lanes[lane].cases.length} highest priority of {data.lanes[lane].count}.{" "}
                {data.lanes[lane].cases.length < 200 && <button onClick={() => more(lane)}>Show more</button>}
              </p>
            )}
          </section>
        ))}
      </div>
    </>
  );
}

export default function Page() {
  return <RequireRole><Today /></RequireRole>;
}
