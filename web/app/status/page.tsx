"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

interface Ready { status: string; checks: Record<string, string | number> }

const MEANING: Record<string, [string, (v: string | number) => boolean]> = {
  storage: ["Where cases and the event log are stored", (v) => v !== "down"],
  pathways: ["Published pathways loaded and matching LOCK.json", (v) => typeof v === "number"],
  templates: ["Approved patient message templates loaded and matching LOCK.json", (v) => typeof v === "number"],
  auth_mode: ["How people sign in", () => true],
  ai: ["Model used for staff call guides (drafts only)", () => true],
};

export default function Status() {
  const [data, setData] = useState<Ready | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [checked, setChecked] = useState<string>("");
  useEffect(() => {
    api<Ready>("/ready", {}).then((r) => { setData(r); setChecked(new Date().toLocaleString()); })
      .catch((e: ApiError) => setErr(e.message));
  }, []);
  return (
    <>
      <h1>System status</h1>
      {err && <p className="error" role="alert">API not ready: {err}</p>}
      {!data && !err && <p>Checking…</p>}
      {data && (
        <>
          <p className={data.status === "ready" ? "ok" : "error"}>{data.status === "ready" ? "✓ Ready" : "Not ready"}
            <span className="muted"> · checked {checked}</span></p>
          <table>
            <thead><tr><th>Check</th><th>Value</th><th>What it means</th><th>OK?</th></tr></thead>
            <tbody>
              {Object.entries(data.checks).map(([k, v]) => {
                const [meaning, ok] = MEANING[k] ?? ["", () => true];
                return (
                  <tr key={k}>
                    <td>{k.replace(/_/g, " ")}</td><td><code>{String(v)}</code></td><td>{meaning}</td>
                    <td className={ok(v) ? "ok" : "error"}>{ok(v) ? "Yes" : "No"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
