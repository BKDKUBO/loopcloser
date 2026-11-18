"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";

const STAFF = new Set(["worker", "coordinator", "supervisor"]);

/** Name and phone stay hidden until a staff member clicks. The API logs each reveal as an event (rule PRIV-1). */
export function RevealContact({ caseId, synthetic, onLogged, callHold }: {
  caseId: string; synthetic: boolean; onLogged: () => void; callHold?: string | null;
}) {
  const s = useSession();
  const [shown, setShown] = useState<{ name?: string; phone?: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!s.role || !STAFF.has(s.role)) return null;
  if (!synthetic) return <span className="muted">Name and phone: not stored in this build.</span>;

  async function reveal() {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ name: string; phone: string }>(`/api/cases/${encodeURIComponent(caseId)}/reveal-contact`,
        await s.headers(), { method: "POST", body: JSON.stringify({ fields: ["name", "phone"] }) });
      setShown(r); onLogged();
    } catch (e) {
      const x = e as ApiError;
      setErr(x.ruleId ? `${x.message} (rule ${x.ruleId})` : x.message);
    } finally { setBusy(false); }
  }

  return (
    <span className="reveal">
      {shown ? (
        <span><strong>{shown.name || "No name on file"}</strong> · {shown.phone || "no valid phone"}{" "}
          <span className="muted">(fictional · this view was logged)</span>{" "}
          {shown.phone && (callHold
            ? <span className="pending">Call on hold: {callHold} (rule GATE-1)</span>
            : <><a className="tel" href={`tel:${shown.phone.replace(/[^+\d]/g, "")}`}
              title="Opens the phone app on your own phone or computer. LoopCloser places no call itself.">Call on my phone</a>{" "}
              <span className="muted small">then log the result under Contact.</span></>)}{" "}
          <button onClick={() => setShown(null)}>Hide</button></span>
      ) : (
        <button disabled={busy} onClick={reveal} aria-describedby="reveal-note">Show name and phone</button>
      )}
      {!shown && <span id="reveal-note" className="muted"> Hidden by default. Each view is logged.</span>}
      {err && <span className="error" role="alert"> {err}</span>}
    </span>
  );
}
