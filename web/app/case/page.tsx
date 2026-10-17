"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { humanState } from "@/lib/lanes";
import type { CaseEvent, CaseView } from "@/lib/types";

function CaseDetail() {
  const id = useSearchParams().get("id") ?? "";
  const s = useSession();
  const [c, setC] = useState<CaseView | null>(null);
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      const h = await s.headers();
      try {
        setC(await api<CaseView>(`/api/cases/${encodeURIComponent(id)}`, h));
        if (s.role !== "patient") setEvents(await api<CaseEvent[]>(`/api/cases/${encodeURIComponent(id)}/events`, h));
      } catch (e) { setErr((e as Error).message); }
    })();
  }, [id, s]);

  if (!id) return <p>No case selected.</p>;
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!c) return <p>Loading…</p>;
  return (
    <>
      <h1>Case {c.id} · {c.participant_id}</h1>
      <p>
        <span className="badge">{humanState(c.state)}</span>
        <span className={`badge ${c.clinical_urgency === "urgent" ? "urgent" : ""}`}>Clinical urgency: {c.clinical_urgency}</span>
        <span className="badge pending">Pathway {c.pathway_id} v{c.pathway_version}: pending clinical sign-off</span>
      </p>
      <p><strong>Next action:</strong> {c.next_action} (due {c.due_date ?? "not set"}) · Owner: {c.owner ?? "none"}</p>
      {c.data_quality.length > 0 && <p className="error">Data quality: {c.data_quality.join(", ")}</p>}
      <h2>Timeline (event log)</h2>
      {events.length === 0 ? <p className="muted">No events visible for your role.</p> : (
        <ol>
          {events.map((e) => (
            <li key={e.id}>
              <strong>{e.type.replace(/_/g, " ")}</strong>
              {typeof e.payload.to === "string" && <> to {humanState(e.payload.to)}</>}
              {" "}<span className="muted">by {e.actor.id} ({e.actor.role}) at {new Date(e.at).toLocaleString()}
                {e.rule_id && <> · rule {e.rule_id}</>}</span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

export default function Page() {
  return <RequireRole><Suspense fallback={<p>Loading…</p>}><CaseDetail /></Suspense></RequireRole>;
}
