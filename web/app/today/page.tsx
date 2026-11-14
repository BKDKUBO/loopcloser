"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CaseActions } from "@/components/CaseActions";
import { PriorityBadge, WhyPriority } from "@/components/Priority";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { LANE_LABELS, type Lane } from "@/lib/lanes";
import { SCREENING_LABELS, dueText, label, ownerLabel, summarySentence, type Summary } from "@/lib/labels";
import type { CaseView } from "@/lib/types";

interface LaneBody { count: number; cases: CaseView[] }
interface TodayResponse {
  total: number; today: string; tier_counts: Record<string, number>; lanes: Record<Lane, LaneBody>; summary: Summary;
}
const PER_LANE = 15;
const STAFF_WITH_CASES = new Set(["worker", "coordinator", "supervisor"]);

function plural(n: number, one: string, many = `${one}s`) { return `${n} ${n === 1 ? one : many}`; }


function CaseCard({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const closed = c.state === "closed";
  const overdue = (c.days_to_due ?? 0) < 0 && !closed && c.plain_status !== "done";
  return (
    <article className="card" aria-label={`Case ${c.id}`}>
      <div>
        <PriorityBadge p={c.priority} />
        {c.clinical_urgency === "urgent" && <span className="badge urgent">Clinically urgent</span>}
        {c.red_flag_open && <span className="badge urgent">Red flag: automation paused</span>}
      </div>
      <strong><Link href={`/case?id=${encodeURIComponent(c.id)}`}>{c.id}</Link></strong>
      {" · "}{label(SCREENING_LABELS, c.screening_type)}
      <div><span className={`status status-${c.plain_status}`}>{c.plain_status_label}</span>
        {c.lost_contact && <span className="badge urgent">Lost contact</span>}</div>
      <div className={overdue ? "urgent" : "muted"}>
        {c.plain_status === "done" ? "Visit done" : dueText(c.days_to_due, closed)} · {ownerLabel(c.owner)}
      </div>
      <WhyPriority p={c.priority} />
      <CaseActions c={c} onChange={onChange} compact />
    </article>
  );
}

function Today() {
  const s = useSession();
  const [data, setData] = useState<TodayResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [mine, setMine] = useState(false);
  const [type, setType] = useState("");
  const [q, setQ] = useState("");
  const [found, setFound] = useState<CaseView[] | null>(null);
  const [searchErr, setSearchErr] = useState<string | null>(null);
  const canMine = s.role !== null && STAFF_WITH_CASES.has(s.role) && s.role !== "worker";

  const qs = `per_lane=${PER_LANE}${mine ? "&mine=true" : ""}${type ? `&screening_type=${type}` : ""}`;
  const load = useCallback(async () => {
    try { setErr(null); setData(await api<TodayResponse>(`/api/today?${qs}`, await s.headers())); }
    catch (e) { setErr((e as Error).message); }
  }, [s, qs]);
  useEffect(() => { load(); }, [load]);

  const replace = (c: CaseView) => {
    setFound((f) => f && f.map((x) => (x.id === c.id ? c : x)));
    setData((d) => d && {
      ...d,
      lanes: Object.fromEntries(Object.entries(d.lanes).map(([k, v]) =>
        [k, { ...v, cases: v.cases.map((x) => (x.id === c.id ? c : x)) }])) as Record<Lane, LaneBody>,
    });
  };

  async function more(lane: Lane) {
    if (!data) return;
    const n = Math.min(data.lanes[lane].cases.length + 25, 200);
    const extra = `${mine ? "&mine=true" : ""}${type ? `&screening_type=${type}` : ""}`;
    const r = await api<{ cases: CaseView[] }>(`/api/cases?lane=${lane}&limit=${n}${extra}`, await s.headers());
    setData((d) => d && { ...d, lanes: { ...d.lanes, [lane]: { ...d.lanes[lane], cases: r.cases } } });
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    setSearchErr(null);
    if (q.trim().length < 2) { setFound(null); return; }
    try {
      const r = await api<{ cases: CaseView[] }>(`/api/cases/search?q=${encodeURIComponent(q.trim())}`, await s.headers());
      setFound(r.cases);
    } catch (x) { setSearchErr((x as Error).message); }
  }

  async function admin(path: string, body: unknown, done: string) {
    setBusy(true);
    setMsg(`${done}: working…`);
    try {
      const r = await api<Record<string, unknown>>(path, await s.headers(), { method: "POST", body: JSON.stringify(body) });
      const l = r.ladder as Record<string, number> | undefined;
      setMsg(l ? `${done}. Today is ${r.today}. Escalation ladder: ${l.steps_run} steps on ${l.cases_touched} cases, ${l.reindexed} priorities refreshed.`
        : r.opened !== undefined ? `${done}: ${r.opened} SIMULATED patients and ${r.stories ?? 0} scripted demo stories.` : `${done}.`);
      await load();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }

  if (err) return <p className="error" role="alert">{err}</p>;
  if (!data) return <p>Loading cases…</p>;

  return (
    <>
      <h1>Today <span className="muted">({data.today})</span></h1>
      <p className="notice" role="note">Demo data: every patient, name and phone number here is fictional (SIMULATED).
        No real SMS is ever sent.</p>
      <p className="summary" aria-live="polite"><strong>{summarySentence(data.summary)}</strong>{" "}
        <span className="muted">{plural(data.total, "case")} {mine ? "assigned to you" : "you can see"}{type ? `, ${label(SCREENING_LABELS, type)} only` : ""}.</span></p>
      <p>
        {(["urgent", "high", "moderate", "routine"] as const).map((t) => (
          <span key={t} className={`badge tier-${t}`}>{t[0].toUpperCase() + t.slice(1)}: {data.tier_counts[t] ?? 0}</span>
        ))}
      </p>
      <div className="row filters" role="search" aria-label="Filter cases">
        {canMine && (
          <label><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> My cases</label>
        )}
        <label>Screening{" "}
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All types</option>
            {Object.entries(SCREENING_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <form onSubmit={search} className="row" style={{ marginTop: 0 }}>
          <label>Find a case{" "}
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Case id, e.g. DEMO-01" aria-label="Case id" />
          </label>
          <button type="submit">Search</button>
          {found && <button type="button" onClick={() => { setFound(null); setQ(""); }}>Clear</button>}
        </form>
      </div>
      <p className="muted">Search is by case id only. Names stay hidden until you open a case and choose to show them; each view is logged.</p>
      {searchErr && <p className="error" role="alert">{searchErr}</p>}
      {found && (
        <section aria-labelledby="found-h" className="card">
          <h2 id="found-h">Search results ({found.length})</h2>
          {found.length === 0 && <p className="muted">No case you can see starts with that id.</p>}
          <div className="lanes">{found.map((c) => <CaseCard key={c.id} c={c} onChange={replace} />)}</div>
        </section>
      )}
      {s.role === "supervisor" && s.demoMode && (
        <div className="card demo row" aria-label="Demo controls">
          <strong>Demo controls:</strong>
          {data.total === 0 && <button disabled={busy} onClick={() => admin("/api/demo/seed", { n: 1000 }, "Loaded")}>Load 1,000 SIMULATED patients and 13 demo stories</button>}
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
            {data.lanes[lane].cases.map((c) => <CaseCard key={c.id} c={c} onChange={replace} />)}
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
