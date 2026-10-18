"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { useCaseAction } from "@/lib/useCaseAction";
import { DEMO_STAFF, type CaseView, type RenderedMessage } from "@/lib/types";

const TEMPLATES = [
  { id: "result-notice", label: "Result notice (4 parts)" },
  { id: "sms-minimal", label: "Minimal SMS (no details)" },
  { id: "reminder", label: "Reminder" },
  { id: "booking-confirmation", label: "Booking confirmation" },
  { id: "emergency-guidance", label: "Emergency guidance" },
];

type Panel = null | "call" | "message" | "assign";

/** [Call] [Message] [Assign] plus the one recommended action. Used on Today cards and the case page. */
export function CaseActions({ c, onChange, compact = false }: { c: CaseView; onChange: (c: CaseView) => void; compact?: boolean }) {
  const s = useSession();
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [panel, setPanel] = useState<Panel>(null);
  const [tpl, setTpl] = useState("result-notice");
  const [lang, setLang] = useState(c.language === "fil" ? "fil" : "en");
  const [preview, setPreview] = useState<RenderedMessage | null>(null);
  const [owner, setOwner] = useState(c.owner ?? DEMO_STAFF[0]);
  const canAssign = s.role === "coordinator" || s.role === "supervisor";
  const ra = c.recommended_action;
  const closed = c.state === "closed";

  async function doRecommended() {
    if (!ra) return;
    if (ra.kind === "contact") return setPanel("call");
    if (ra.kind === "assign") return setPanel("assign");
    if (ra.kind === "transition" && ra.target && ra.target !== "action_scheduled") {
      const body: Record<string, unknown> = { target: ra.target };
      if (ra.target === "understanding_confirmed") body.source = "staff_confirmed";
      await run(`/api/cases/${c.id}/transition`, body, undefined, "Done.");
    }
  }
  const recommendedInline = ra && ((ra.kind === "transition" && ra.target && ra.target !== "action_scheduled")
    || ra.kind === "contact" || ra.kind === "assign");

  async function loadPreview(t = tpl, l = lang) {
    try {
      setPreview(await api<RenderedMessage>(`/api/cases/${c.id}/messages/preview`, await s.headers(),
        { method: "POST", body: JSON.stringify({ template_id: t, language: l }) }));
    } catch (e) { setPreview(null); alert((e as Error).message); }
  }

  if (closed) return <p className="muted">Case closed.</p>;
  return (
    <div>
      {ra && (
        <p><strong>Recommended:</strong> {ra.label}{" "}
          {recommendedInline ? (
            <button className="primary" disabled={busy} onClick={doRecommended}>Do it</button>
          ) : compact ? <Link href={`/case?id=${encodeURIComponent(c.id)}`}>Open case</Link> : null}
        </p>
      )}
      <div className="row" role="group" aria-label="Case actions">
        <button onClick={() => setPanel(panel === "call" ? null : "call")} aria-expanded={panel === "call"}>Call</button>
        <button onClick={() => { setPanel(panel === "message" ? null : "message"); loadPreview(); }}
          aria-expanded={panel === "message"}>Message</button>
        {canAssign && <button onClick={() => setPanel(panel === "assign" ? null : "assign")}
          aria-expanded={panel === "assign"}>Assign</button>}
      </div>

      {panel === "call" && (
        <div className="row" aria-label="Call result">
          <span>Call result:</span>
          {[["reached", "Reached"], ["no_answer", "No answer"], ["invalid_number", "Invalid number"]].map(([v, l]) => (
            <button key={v} disabled={busy} onClick={() => run(`/api/cases/${c.id}/contact-attempts`,
              { channel: "call", result: v }, undefined, `Call logged: ${l}.`).then(() => setPanel(null))}>{l}</button>
          ))}
        </div>
      )}

      {panel === "message" && (
        <div>
          <div className="row">
            <label>Template{" "}
              <select value={tpl} onChange={(e) => { setTpl(e.target.value); loadPreview(e.target.value, lang); }}>
                {TEMPLATES.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </label>
            <label>Language{" "}
              <select value={lang} onChange={(e) => { setLang(e.target.value); loadPreview(tpl, e.target.value); }}>
                <option value="en">English</option><option value="fil">Filipino</option>
              </select>
            </label>
          </div>
          {preview && (
            <div className="msg">
              <p>{preview.text}</p>
              <p className="muted pending">Approved template {preview.template_id} v{preview.template_version}:
                pending review. {preview.review_note}</p>
            </div>
          )}
          <button className="primary" disabled={busy || !preview} onClick={() => run<{ case: CaseView }>(
            `/api/cases/${c.id}/messages`, { template_id: tpl, language: lang, channel: "sms" }, (r) => r.case,
            "Message logged in the simulated outbox. No real SMS was sent.").then(() => setPanel(null))}>
            Send (simulated)
          </button>
          <p className="muted">Official messages only come from approved templates. AI never writes or sends them.</p>
        </div>
      )}

      {panel === "assign" && canAssign && (
        <div className="row">
          <label>Owner{" "}
            <select value={owner} onChange={(e) => setOwner(e.target.value)}>
              {DEMO_STAFF.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </label>
          <button className="primary" disabled={busy} onClick={() => run(`/api/cases/${c.id}/assign`, { owner },
            undefined, `Assigned to ${owner}.`).then(() => setPanel(null))}>Assign</button>
        </div>
      )}
      {notice && <p className="ok" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
