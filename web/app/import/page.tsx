"use client";

import Link from "next/link";
import { useState } from "react";
import { ConfirmButton } from "@/components/ConfirmButton";
import { RequireRole } from "@/components/RequireRole";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";

interface Summary { total_rows: number; valid_rows: number; rows_with_errors: number; rows_with_warnings: number; file_errors: string[] }
interface Validate { summary: Summary; issues_preview: { line: number; record_id: string | null; errors: string[]; warnings: string[] }[]; error_csv: string }

const COLUMNS = "record_id, participant_id, screening_type, result, severity, screened_at, language (required); owner, phone, comorbidity, barrier, red_flag, location, age_band (optional)";
const EXAMPLE = `record_id,participant_id,screening_type,result,severity,screened_at,language,owner
R-IMPORT-1,P-500001,fit,positive,abnormal,2026-11-10,fil,demo-worker-01
R-IMPORT-2,P-500002,bp,elevated,abnormal,2026-11-12,en,
R-IMPORT-3,P-500003,cervical,abnormal,abnormal,not-a-date,en,demo-worker-02
`;

function Import() {
  const s = useSession();
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [report, setReport] = useState<Validate | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const allowed = s.role === "coordinator" || s.role === "supervisor";

  async function post<T>(path: string): Promise<T | null> {
    setBusy(true); setErr(null);
    try {
      const h = await s.headers();
      return await api<T>(path, { ...h, "content-type": "text/csv" }, { method: "POST", body: text });
    } catch (e) {
      const x = e as ApiError; setErr(x.message); return null;
    } finally { setBusy(false); }
  }

  if (!allowed) return <p>Only a coordinator or supervisor can import results.</p>;
  const download = report ? `data:text/csv;charset=utf-8,${encodeURIComponent(report.error_csv)}` : "";
  return (
    <>
      <h1>Import screening results (CSV)</h1>
      <p>Check a file first: every row is validated, and only rows without errors can be imported. Normal results are skipped.
        Each imported row opens a case through the same rules as the API. <strong>Use fictional data only in this demo.</strong>{" "}
        Names and phone numbers in a real file are not stored by this build.</p>
      <p className="muted small">Columns: {COLUMNS}. UTF-8, 5 MB at most.</p>
      <p className="small">Have a lab result as a FHIR R4 Bundle instead? <Link href="/fhir">Import FHIR</Link>.</p>
      <div className="row">
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={async (e) => {
          const f = e.target.files?.[0]; if (!f) return;
          setFileName(f.name); setText(await f.text()); setReport(null); setResult(null);
        }} />
        <button onClick={() => { setText(EXAMPLE); setFileName("example (fictional)"); setReport(null); setResult(null); }}>Use a small fictional example</button>
      </div>
      <label className="block">CSV text{fileName ? ` (${fileName})` : ""}
        <textarea rows={8} value={text} onChange={(e) => { setText(e.target.value); setReport(null); setResult(null); }} style={{ width: "100%", fontFamily: "monospace" }} />
      </label>
      <div className="row">
        <button className="primary" disabled={busy || !text.trim()} onClick={async () => { setResult(null); setReport(await post<Validate>("/api/imports/validate")); }}>Check file</button>
        <ConfirmButton disabled={busy || !report || report.summary.valid_rows === 0 || report.summary.file_errors.length > 0}
          confirm={`Open cases for ${report?.summary.valid_rows ?? 0} valid rows?`}
          onConfirm={async () => {
            const r = await post<{ opened: number; skipped: number }>("/api/imports/commit");
            if (r) setResult(`Imported: ${r.opened} cases opened, ${r.skipped} skipped (normal result, no matching pathway, or already imported).`);
          }}>Import valid rows</ConfirmButton>
      </div>
      {err && <p className="error" role="alert">{err}</p>}
      {result && <p className="ok" role="status">{result}</p>}
      {report && (
        <section aria-labelledby="rep">
          <h2 id="rep">Check result</h2>
          <table><tbody>
            <tr><th>Rows</th><td>{report.summary.total_rows}</td></tr>
            <tr><th>Valid (importable)</th><td>{report.summary.valid_rows}</td></tr>
            <tr><th>With errors (not imported)</th><td className={report.summary.rows_with_errors ? "error" : ""}>{report.summary.rows_with_errors}</td></tr>
            <tr><th>With warnings</th><td>{report.summary.rows_with_warnings}</td></tr>
          </tbody></table>
          {report.summary.file_errors.length > 0 && <p className="error">File problems: {report.summary.file_errors.join("; ")}</p>}
          {report.issues_preview.length > 0 && (
            <>
              <h3>Rows with problems</h3>
              <table><thead><tr><th>Line</th><th>Record</th><th>Errors</th><th>Warnings</th></tr></thead>
                <tbody>{report.issues_preview.slice(0, 50).map((r) => (
                  <tr key={r.line}><td>{r.line}</td><td>{r.record_id}</td><td className="error">{r.errors.join("; ")}</td><td>{r.warnings.join("; ")}</td></tr>
                ))}</tbody></table>
              <p><a href={download} download="loopcloser-import-issues.csv">Download all issues as CSV</a></p>
            </>
          )}
        </section>
      )}
    </>
  );
}

export default function Page() {
  return <RequireRole><Import /></RequireRole>;
}
