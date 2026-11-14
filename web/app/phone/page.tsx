"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { LANGUAGE_LABELS, label, words } from "@/lib/labels";

interface Msg { at: string; template_id: string; language: string; channel: string; by_automation: boolean; text: string | null }
interface Outbox { case_id: string; participant_id: string; language: string; messages: Msg[] }

/** What the patient's phone would show. Simulated: nothing is ever sent. */
function Phone() {
  const id = useSearchParams().get("id") ?? "C-DEMO-01";
  const s = useSession();
  const [o, setO] = useState<Outbox | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    s.headers().then((h) => api<Outbox>(`/api/cases/${encodeURIComponent(id)}/outbox`, h)).then(setO).catch((e: Error) => setErr(e.message));
  }, [id, s]);
  return (
    <>
      <h1>The patient&apos;s phone <span className="muted">(simulated)</span></h1>
      <p>Case <Link href={`/case?id=${encodeURIComponent(id)}`}>{id}</Link>. Every SMS LoopCloser logged for this patient, in the
        language on file, from approved templates only. <strong>No real SMS is sent</strong>; the phone below is a mock-up.</p>
      {err && <p className="error" role="alert">{err}</p>}
      {o && (
        <div className="phone" role="img" aria-label="Phone showing the SMS messages">
          <div className="phone-notch" />
          <div className="phone-top"><strong>Health Center</strong><div className="small">(demo sender · SIMULATED)</div></div>
          <div className="phone-screen">
            {o.messages.length === 0 && <p className="muted small">No messages yet.</p>}
            {o.messages.map((m, i) => (
              <div key={i} className="sms">
                <div>{m.text ?? `[${words(m.template_id)} template]`}</div>
                <div className="sms-meta">{new Date(m.at).toLocaleString()} · {label(LANGUAGE_LABELS, m.language)} · {m.by_automation ? "automatic reminder" : "sent by staff"}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {o && (
        <p className="muted small">Texts are re-rendered from the logged template id, version and language with today&apos;s case
          record. Templates are pending clinical and native Filipino speaker review.</p>
      )}
    </>
  );
}

export default function Page() {
  return <RequireRole><Suspense fallback={<p>Loading…</p>}><Phone /></Suspense></RequireRole>;
}
