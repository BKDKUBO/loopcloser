"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ConfirmButton } from "@/components/ConfirmButton";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/auth";
import { CONTACT_RESULT_LABELS, LANGUAGE_LABELS, STATE_LABELS, label } from "@/lib/labels";
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

/**
 * [Call] [Message] [Assign] (+ an optional slot, e.g. "Prepare for the call"), plus the one recommended
 * action on Today cards. The case page shows the recommended action in its own panel, so it passes
 * showRecommended={false} to avoid a second "Do it" button.
 */
export function CaseActions({ c, onChange, compact = false, showRecommended = true, extra }: {
  c: CaseView; onChange: (c: CaseView) => void; compact?: boolean; showRecommended?: boolean; extra?: ReactNode;
}) {
  const s = useSession();
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [panel, setPanel] = useState<Panel>(null);
  const [tpl, setTpl] = useState("result-notice");
  const [lang, setLang] = useState(c.language === "fil" ? "fil" : "en");
  const [preview, setPreview] = useState<RenderedMessage | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [owner, setOwner] = useState(c.owner ?? DEMO_STAFF[0]);
  const canAssign = s.role === "coordinator" || s.role === "supervisor";
  const ra = c.recommended_action;
  const closed = c.state === "closed";

  async function doRecommended() {
    if (!ra) return;
    if (ra.kind === "transition" && ra.target && ra.target !== "action_scheduled") {
      const body: Record<string, unknown> = { target: ra.target };
      if (ra.target === "understanding_confirmed") body.source = "staff_confirmed";
      await run(`/api/cases/${c.id}/transition`, body, undefined, `Done: ${label(STATE_LABELS, ra.target)}. Logged in the timeline.`);
    }
  }
  const oneClick = ra && ra.kind === "transition" && ra.target && ra.target !== "action_scheduled";
  const opensPanel = ra && (ra.kind === "contact" || ra.kind === "assign");

  async function loadPreview(t = tpl, l = lang) {
    setPreviewErr(null);
    try {
      setPreview(await api<RenderedMessage>(`/api/cases/${c.id}/messages/preview`, await s.headers(),
        { method: "POST", body: JSON.stringify({ template_id: t, language: l }) }));
    } catch (e) {
      const x = e as ApiError;
      setPreview(null);
      setPreviewErr(x.ruleId ? `${x.message} (rule ${x.ruleId})` : x.message);
    }
  }

  if (closed) return <p className="muted">Case closed.</p>;
  return (
    <div>
      {showRecommended && ra && (
        <p><strong>Next:</strong> {ra.label}{" "}
          {oneClick ? (
            <ConfirmButton primary disabled={busy} confirm={`Mark as "${label(STATE_LABELS, ra.target)}"?`}
              onConfirm={doRecommended}>Do it</ConfirmButton>
          ) : opensPanel ? (
            <button className="primary" onClick={() => setPanel(ra.kind === "contact" ? "call" : "assign")}>Do it</button>
          ) : compact ? <Link href={`/case?id=${encodeURIComponent(c.id)}`}>Open case</Link> : null}
        </p>
      )}
      <div className="row" role="group" aria-label="Case actions">
        <button onClick={() => setPanel(panel === "call" ? null : "call")} aria-expanded={panel === "call"}>Call</button>
        {extra}
        <button onClick={() => { setPanel(panel === "message" ? null : "message"); if (panel !== "message") loadPreview(); }}
          aria-expanded={panel === "message"}>Message</button>
        {canAssign && <button onClick={() => setPanel(panel === "assign" ? null : "assign")}
          aria-expanded={panel === "assign"}>Assign</button>}
      </div>

      {panel === "call" && (
        <div className="row" aria-label="Call result">
          <span>Call result:</span>
          {(["reached", "no_answer", "invalid_number"] as const).map((v) => (
            <ConfirmButton key={v} disabled={busy} confirm={`Log "${CONTACT_RESULT_LABELS[v]}"?`}
              onConfirm={() => run(`/api/cases/${c.id}/contact-attempts`, { channel: "call", result: v }, undefined,
                `Call logged: ${CONTACT_RESULT_LABELS[v]}.`).then(() => setPanel(null))}>
              {CONTACT_RESULT_LABELS[v]}
            </ConfirmButton>
          ))}
          <button onClick={() => setPanel(null)}>Cancel</button>
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
                <option value="en">{LANGUAGE_LABELS.en}</option><option value="fil">{LANGUAGE_LABELS.fil}</option>
              </select>
            </label>
          </div>
          {previewErr && <p className="error" role="alert">Cannot preview this message: {previewErr}</p>}
          {preview && (
            <div className="msg">
              <p>{preview.text}</p>
              <p className="muted pending">Approved template {preview.template_id} v{preview.template_version}:
                pending review. {preview.review_note}</p>
            </div>
          )}
          <ConfirmButton primary disabled={busy || !preview} confirm="Log this message in the simulated outbox?"
            onConfirm={() => run<{ case: CaseView }>(`/api/cases/${c.id}/messages`, { template_id: tpl, language: lang, channel: "sms" },
              (r) => r.case, "Message logged in the simulated outbox. No real SMS was sent.").then(() => setPanel(null))}>
            Send (simulated)
          </ConfirmButton>
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
          <ConfirmButton primary disabled={busy} confirm={`Make ${owner} the owner?`}
            onConfirm={() => run(`/api/cases/${c.id}/assign`, { owner }, undefined, `Assigned to ${owner}.`).then(() => setPanel(null))}>
            Assign
          </ConfirmButton>
        </div>
      )}
      {notice && <p className="ok" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
