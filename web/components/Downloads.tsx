"use client";

import Link from "next/link";
import { useState } from "react";
import { useSession } from "@/lib/auth";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";
const STAFF = new Set(["worker", "coordinator", "supervisor", "program_manager"]);

/** Staff-only downloads (rule PRIV-2). Each download is logged as an event; files mask the participant id. */
export function Downloads({ caseId, onLogged }: { caseId: string; onLogged: () => void }) {
  const s = useSession();
  const [error, setError] = useState<string | null>(null);
  if (!s.role || !STAFF.has(s.role)) return null;
  const id = encodeURIComponent(caseId);

  async function download(ext: "csv" | "json") {
    setError(null);
    try {
      const res = await fetch(`${BASE}/api/cases/${id}/export/audit.${ext}`, { headers: await s.headers() });
      if (!res.ok) throw new Error(`Download failed (${res.status}).`);
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${caseId}-audit-trail.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
      onLogged();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <section aria-labelledby="dl-h">
      <h2 id="dl-h">Download</h2>
      <div className="row">
        <Link className="button" href={`/case/print?id=${id}`}>Printable summary (Save as PDF)</Link>
        <button onClick={() => download("csv")}>Audit trail (CSV)</button>
        <button onClick={() => download("json")}>Audit trail (JSON)</button>
      </div>
      <p className="muted small">Staff only. Every download is logged in the timeline (rule PRIV-2). Files mask the
        participant id and never contain names or phone numbers.</p>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
