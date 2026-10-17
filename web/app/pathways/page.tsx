"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/RequireRole";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";

interface Pathway {
  id: string; version: string; name: string; scope: string; next_action: string;
  default_deadline_days: number; deadline_label: string; sources: string[]; signoff_status: string;
}

function Pathways() {
  const s = useSession();
  const [rows, setRows] = useState<Pathway[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    s.headers().then((h) => api<Pathway[]>("/api/pathways", h)).then(setRows).catch((e: Error) => setErr(e.message));
  }, [s]);
  if (err) return <p className="error" role="alert">{err}</p>;
  if (!rows) return <p>Loading…</p>;
  return (
    <>
      <h1>Pathway library</h1>
      <p className="pending"><strong>All pathways are pending clinical sign-off.</strong> Deadlines are configurable
        defaults pending clinical review.</p>
      <table>
        <thead><tr><th>Pathway</th><th>Next action</th><th>Default deadline</th><th>Sources</th></tr></thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id}>
              <td>{p.name}<br /><span className="muted">{p.id} v{p.version} · {p.scope}</span></td>
              <td>{p.next_action}</td>
              <td>{p.default_deadline_days} days<br /><span className="muted">{p.deadline_label}</span></td>
              <td>{p.sources.map((u) => <div key={u}><a href={u} target="_blank" rel="noreferrer">{new URL(u).hostname}</a></div>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export default function Page() {
  return <RequireRole><Pathways /></RequireRole>;
}
