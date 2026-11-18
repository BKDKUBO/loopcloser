"use client";

import Link from "next/link";
import { useState } from "react";
import { ConfirmButton } from "@/components/ConfirmButton";
import { RequireRole } from "@/components/RequireRole";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { SCREENING_LABELS, label } from "@/lib/labels";
import type { CaseView } from "@/lib/types";

interface Item {
  resource: string; status: "ready" | "skipped" | "error" | "opened"; messages: string[]; case_id?: string;
  screening_type?: string; result?: string; severity?: string; screened_at?: string; code?: string | null;
  interpretation?: string | null; referral?: string;
}
interface Checked { synthetic: boolean; warnings: string[]; items: Item[]; opened?: CaseView[] }

const SAMPLES: { id: string; label: string }[] = [
  { id: "fit", label: "Positive FIT (bowel screening)" },
  { id: "cervical", label: "High-risk HPV (cervical screening)" },
  { id: "bp", label: "High blood pressure" },
];
const STATUS_LABEL: Record<Item["status"], string> = {
  ready: "Ready to open", skipped: "Not opened", error: "Error", opened: "Case opened",
};

/** Paste a FHIR R4 Bundle, or load a SYNTHETIC sample, and a case appears. No FHIR server is called. */
function FhirImport() {
  const s = useSession();
  const [text, setText] = useState("");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const allowed = s.role === "coordinator" || s.role === "supervisor";

  async function call<T>(path: string, init: RequestInit = {}): Promise<T | null> {
    setBusy(true); setErr(null);
    try { return await api<T>(path, await s.headers(), init); }
    catch (e) { const x = e as ApiError; setErr(x.message); return null; }
    finally { setBusy(false); }
  }
  async function loadSample(kind: string) {
    const b = await call<unknown>(`/api/fhir/sample?kind=${kind}`);
    if (b) { setText(JSON.stringify(b, null, 2)); setChecked(null); }
  }
  async function check() {
    let body: string;
    try { body = JSON.stringify(JSON.parse(text)); }
    catch { setErr("This is not valid JSON. Paste a FHIR R4 Bundle in JSON format."); return; }
    setChecked(await call<Checked>("/api/fhir/import/validate", { method: "POST", body }));
  }
  async function importNow() {
    const r = await call<Checked>("/api/fhir/import", { method: "POST", body: JSON.stringify(JSON.parse(text)) });
    if (r) setChecked(r);
  }

  if (!allowed) return <p>Only a coordinator or supervisor can import results.</p>;
  const ready = checked?.items.filter((i) => i.status === "ready").length ?? 0;
  return (
    <>
      <h1>Import a lab result (FHIR R4)</h1>
      <p>Paste a <strong>FHIR R4 Bundle</strong> (JSON) with a <code>Patient</code> and an <code>Observation</code> or{" "}
        <code>DiagnosticReport</code>, optionally a <code>ServiceRequest</code> (the referral). Each final, flagged result opens a
        case through the same rules as every other case. Or load a synthetic sample and import it in two clicks.</p>
      <p className="pending small">Honest scope: there is <strong>no live EHR or lab connection</strong> in this build and no FHIR
        server is called. The Bundle you paste is read here and nothing else. <strong>Use synthetic data only</strong>: this is a
        public demo. Names, phone numbers and addresses in the Bundle are never stored; consent to contact is never read from a
        Bundle, so calls and SMS stay on hold until a person records it (rule GATE-1).</p>
      <div className="row">
        {SAMPLES.map((x) => (
          <button key={x.id} disabled={busy} onClick={() => loadSample(x.id)}>Load sample bundle: {x.label}</button>
        ))}
      </div>
      <label className="block">FHIR R4 Bundle (JSON)
        <textarea rows={14} value={text} spellCheck={false} placeholder='{"resourceType": "Bundle", "type": "collection", "entry": [...]}'
          onChange={(e) => { setText(e.target.value); setChecked(null); }} style={{ width: "100%", fontFamily: "monospace", fontSize: "0.85em" }} />
      </label>
      <div className="row">
        <button className="primary" disabled={busy || !text.trim()} onClick={check}>Check bundle</button>
        <ConfirmButton disabled={busy || !checked || ready === 0 || !!checked.opened}
          confirm={`Open ${ready} case${ready === 1 ? "" : "s"} from this bundle?`} onConfirm={importNow}>
          Import and open case{ready === 1 ? "" : "s"}
        </ConfirmButton>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      {checked && (
        <section aria-labelledby="res">
          <h2 id="res">{checked.opened ? "Imported" : "Check result"}</h2>
          {checked.warnings.map((w) => <p key={w} className="pending">{w}</p>)}
          {checked.opened && checked.opened.length > 0 && (
            <p className="ok" role="status">Opened {checked.opened.map((c, i) => (
              <span key={c.id}>{i > 0 && ", "}<Link href={`/case?id=${encodeURIComponent(c.id)}`}>{c.id}</Link></span>))}.
              {" "}It is on Today now, unowned and with consent not recorded, like any new result.</p>
          )}
          <table><thead><tr><th>Resource</th><th>Result</th><th>Code (as sent)</th><th>Status</th><th>Notes</th></tr></thead>
            <tbody>{checked.items.map((i) => (
              <tr key={i.resource}>
                <td><code>{i.resource}</code></td>
                <td>{i.screening_type ? <>{label(SCREENING_LABELS, i.screening_type)}: {i.result} ({i.severity}), {i.screened_at}</> : "–"}
                  {i.referral && <div className="muted small">Referral: {i.referral}</div>}</td>
                <td>{i.code ?? "–"}{i.interpretation ? <div className="muted small">interpretation {i.interpretation}</div> : null}</td>
                <td className={i.status === "error" ? "error" : i.status === "opened" ? "ok" : ""}>{STATUS_LABEL[i.status]}
                  {i.case_id && i.status !== "ready" && <> · <Link href={`/case?id=${encodeURIComponent(i.case_id)}`}>{i.case_id}</Link></>}</td>
                <td>{i.messages.join(" ")}</td>
              </tr>))}</tbody></table>
          <p className="muted small">Mapping: LOINC code to screening type from a short table (pending clinical review); the lab&apos;s
            interpretation code (POS, A, H, HH, N…) decides abnormal or normal. LoopCloser never interprets raw values. Only final
            results are imported; normal results open no case.</p>
        </section>
      )}
    </>
  );
}

export default function Page() {
  return <RequireRole><FhirImport /></RequireRole>;
}
