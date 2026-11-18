"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { LANGUAGE_LABELS, label, words } from "@/lib/labels";
import { liveText, useAutoRefresh } from "@/lib/useAutoRefresh";

interface Msg {
  at: string; direction: "out" | "in"; template_id: string | null; language: string; channel: string;
  by_automation: boolean; text: string | null;
}
interface Outbox {
  case_id: string; participant_id: string; language: string; messages: Msg[]; sms_opt_out?: boolean; state?: string;
  can_reply?: boolean;
}

const REPLIES: { keyword: "YES" | "RESCHED" | "STOP"; help: string }[] = [
  { keyword: "YES", help: "Got the message / will come. Marks the patient notified or the booking confirmed. It never counts as understanding (rule MSG-1)." },
  { keyword: "RESCHED", help: "Asks for a new date. A booked or missed visit moves to Rescheduled, so a person calls back." },
  { keyword: "STOP", help: "No more SMS. Takes effect at once; calls and visits still follow consent." },
];

/** What the patient's phone would show. Simulated: nothing is ever sent, and the reply buttons stand in for the
 * patient texting back (rule MSG-4). In production the replies would come from an SMS gateway. */
function Phone() {
  const id = useSearchParams().get("id") ?? "C-DEMO-01";
  const s = useSession();
  const [o, setO] = useState<Outbox | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setO(await api<Outbox>(`/api/cases/${encodeURIComponent(id)}/outbox`, await s.headers())); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, [id, s]);
  useEffect(() => { load(); }, [load]);
  const live = useAutoRefresh(load);

  async function reply(keyword: string) {
    setBusy(true); setErr(null); setNotice(null);
    try {
      await api(`/api/cases/${encodeURIComponent(id)}/sms-replies`, await s.headers(),
        { method: "POST", body: JSON.stringify({ keyword }) });
      setNotice(`Reply ${keyword} logged on case ${id} (simulated). Open the case in another tab: it updates by itself.`);
      await load();
    } catch (e) {
      const x = e as ApiError; setErr(x.ruleId ? `${x.message} (rule ${x.ruleId})` : x.message);
    } finally { setBusy(false); }
  }

  return (
    <>
      <h1>The patient&apos;s phone <span className="muted">(simulated)</span></h1>
      <p>Case <Link href={`/case?id=${encodeURIComponent(id)}`}>{id}</Link>. Every SMS LoopCloser logged for this patient, in the
        language on file, from approved templates only. <strong>No real SMS is sent or received</strong>; the phone below is a
        mock-up, and the reply buttons stand in for the patient texting back.</p>
      <p className={`live ${live.visible ? "" : "paused"}`}>{liveText(live.visible, live.checkedAt)}</p>
      {err && <p className="error" role="alert">{err}</p>}
      {notice && <p className="ok" role="status">{notice}</p>}
      {o && (
        <div className="phone" role="group" aria-label="Phone showing the SMS messages">
          <div className="phone-notch" />
          <div className="phone-top"><strong>Health Center</strong><div className="small">(demo sender · SIMULATED)</div></div>
          <div className="phone-screen">
            {o.messages.length === 0 && <p className="muted small">No messages yet.</p>}
            {o.messages.map((m, i) => (
              <div key={i} className={`sms ${m.direction === "in" ? "in" : ""}`}>
                <div>{m.text ?? `[${words(m.template_id ?? "")} template]`}</div>
                <div className="sms-meta">{new Date(m.at).toLocaleString()} ·{" "}
                  {m.direction === "in" ? "patient reply (simulated)"
                    : `${label(LANGUAGE_LABELS, m.language)} · ${m.by_automation ? "automatic reminder" : "sent by staff"}`}</div>
              </div>
            ))}
            {o.sms_opt_out && <p className="muted small">The patient replied STOP: LoopCloser sends no more SMS (rule MSG-4).</p>}
          </div>
          {o.can_reply && (
            <div className="phone-reply" aria-label="Simulated patient reply">
              {REPLIES.map((r) => (
                <button key={r.keyword} disabled={busy} title={r.help} onClick={() => reply(r.keyword)}>{r.keyword}</button>
              ))}
            </div>
          )}
        </div>
      )}
      {o && o.can_reply && (
        <ul className="muted small">
          {REPLIES.map((r) => <li key={r.keyword}><strong>{r.keyword}</strong>: {r.help}</li>)}
          <li>While a red flag is open, a reply is only logged: a person is handling the case.</li>
        </ul>
      )}
      {o && !o.can_reply && (
        <p className="muted small">{o.state === "closed" ? "The case is closed, so replies are off." : "Nothing was texted yet, so there is nothing to reply to."}</p>
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
