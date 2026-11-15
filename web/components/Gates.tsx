"use client";

import { useState } from "react";
import { KindBadge } from "@/components/Kind";
import { useSession } from "@/lib/auth";
import { gateCounts } from "@/lib/gates";
import { useCaseAction } from "@/lib/useCaseAction";
import type { CaseView } from "@/lib/types";

const CAN_RECORD = new Set(["worker", "coordinator", "supervisor"]);

/** Rule GATE-1: Pass or Hold for each check, with what is missing. The API blocks calls and SMS on a Hold. */
export function Gates({ c, onChange }: { c: CaseView; onChange: (c: CaseView) => void }) {
  const s = useSession();
  const { run, busy, error, notice } = useCaseAction(onChange);
  const [source, setSource] = useState("");
  const gates = c.gates ?? [];
  if (gates.length === 0) return null;
  const { hold } = gateCounts(c);
  const closed = c.state === "closed";
  const consentHold = gates.some((g) => g.id === "consent" && g.status === "hold") && c.contact_consent !== "no";
  return (
    <section aria-labelledby="gates-h" className={`card gates ${hold && !closed ? "gates-hold" : ""}`}>
      <h2 id="gates-h">Checks before contact <KindBadge kind="rule" /></h2>
      <p className="muted small">{closed ? "Case closed." : hold === 0
        ? "All checks pass. A person still reviews the case before contacting the patient."
        : `${hold} on hold. Calls and SMS stay blocked while consent or contact details are on hold (rule GATE-1); nothing is sent automatically.`}</p>
      <ul className="gate-list">
        {gates.map((g) => (
          <li key={g.id} className={`gate gate-${g.status}`}>
            <span className={`gate-status gate-status-${g.status}`}>{g.status === "pass" ? "✓ Pass" : "⏸ Hold"}</span>{" "}
            <strong>{g.label}</strong>: {g.detail}
            {g.status === "hold" && g.missing && <div className="small">Missing: {g.missing}
              {g.blocks.length > 0 && <> Blocks: {g.blocks.map((b) => b === "chw_visit" ? "home visit" : b === "sms" ? "SMS" : b).join(", ")}.</>}</div>}
          </li>
        ))}
      </ul>
      {!closed && consentHold && s.role && CAN_RECORD.has(s.role) && (
        <fieldset>
          <legend>Record consent to contact <KindBadge kind="fact" /></legend>
          <label>How was it obtained? (needed){" "}
            <input value={source} onChange={(e) => setSource(e.target.value)} maxLength={200}
              placeholder="e.g. In person at the home visit" /></label>
          <div className="row">
            <button disabled={busy || !source.trim()} onClick={() => run(`/api/cases/${c.id}/consent`, { consent: "yes", source },
              undefined, "Consent recorded. Logged in the timeline.")}>Patient agreed to be contacted</button>
            <button disabled={busy || !source.trim()} onClick={() => run(`/api/cases/${c.id}/consent`, { consent: "no", source },
              undefined, "Recorded: the patient declined contact.")}>Patient declined contact</button>
          </div>
        </fieldset>
      )}
      {notice && <p className="ok" role="status">{notice}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
