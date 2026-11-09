"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";

interface Draft {
  draft_seq: number; at: string; by: string; label: string; model: string | null; mock: boolean;
  verified: boolean; text: string | null; unsupported: string[]; checked_count: number;
  decision: "use" | "discard" | null; decided_by: string | null;
}

const STAFF = new Set(["worker", "coordinator", "supervisor"]);

/** Staff-only AI call guide. A draft: it never changes the case. Every number and date is checked by the API. */
export function CallPrep({ caseId, disabledReason, onLogged }: { caseId: string; disabledReason?: string; onLogged: () => void }) {
  const s = useSession();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const base = `/api/ai/cases/${encodeURIComponent(caseId)}/call-prep`;

  const load = useCallback(async () => {
    if (!s.role || !STAFF.has(s.role)) return;
    try { setDraft((await api<{ draft: Draft | null }>(base, await s.headers())).draft); } catch { /* optional panel */ }
  }, [base, s]);
  useEffect(() => { load(); }, [load]);

  if (!s.role || !STAFF.has(s.role)) return null;

  async function post(path: string, body?: unknown) {
    setBusy(true); setError(null);
    try {
      const r = await api<{ draft: Draft }>(path, await s.headers(), { method: "POST", body: JSON.stringify(body ?? {}) });
      setDraft(r.draft); onLogged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.ruleId ? `${err.message} (rule ${err.ruleId})` : err.message);
    } finally { setBusy(false); }
  }

  const open = draft && draft.decision === null;
  return (
    <section className="card callprep" aria-labelledby="cp-h">
      <h2 id="cp-h">Prepare for the call <span className="badge">AI draft · staff only</span></h2>
      <p className="muted">Gemini drafts a short guide from this case&apos;s record (no names or phone numbers). It does
        not change the case. Every number and date in it is checked against the record before you see it.</p>
      <button className="primary" disabled={busy || Boolean(disabledReason)} onClick={() => post(base)}>
        {busy ? "Drafting…" : draft ? "Draft again" : "Prepare for the call"}</button>
      {disabledReason && <p className="muted">{disabledReason}</p>}
      {draft && (
        <div style={{ marginTop: 10 }}>
          <p className="pending"><strong>{draft.label}</strong>{" "}
            <span className="muted">({draft.mock ? "offline template, no model" : draft.model}, requested by {draft.by})</span></p>
          {draft.verified ? (
            <>
              <p className="ok">✓ All {draft.checked_count} numbers and dates match the case record.</p>
              <pre className="draft">{draft.text}</pre>
            </>
          ) : (
            <p className="error" role="alert">Draft withheld: it mentioned {draft.unsupported.join(", ")}, which
              {draft.unsupported.length === 1 ? " is" : " are"} not in the case record. Discard it and draft again.</p>
          )}
          {open ? (
            <div className="row">
              <button disabled={busy || !draft.verified} onClick={() => post(`${base}/${draft.draft_seq}/decision`, { decision: "use" })}>Use</button>{" "}
              <button disabled={busy} onClick={() => post(`${base}/${draft.draft_seq}/decision`, { decision: "discard" })}>Discard</button>
            </div>
          ) : (
            <p className="muted">{draft.decision === "use" ? "Used" : "Discarded"} by {draft.decided_by}. Logged in the timeline.</p>
          )}
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
