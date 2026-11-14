import type { CaseEvent } from "./types";
import {
  BARRIER_LABELS, CHANNEL_LABELS, CONTACT_RESULT_LABELS, LANGUAGE_LABELS, OVERRIDE_REASON_LABELS, RED_FLAG_CODES,
  SCREENING_LABELS, STATE_LABELS, label, words,
} from "./labels";

const str = (v: unknown) => (typeof v === "string" ? v : v === null || v === undefined ? "" : String(v));

/** One readable sentence per event. The raw type and rule id are still shown next to it. */
export function describeEvent(e: CaseEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "case_opened":
      return `${label(SCREENING_LABELS, str(p.screening_type))} result (${words(str(p.result))}, ${str(p.severity)}) opened on pathway ${str(p.pathway_id)}. Deadline ${str(p.due_date)}.`;
    case "owner_assigned":
      return [p.owner && `Owner: ${str(p.owner)}`, p.backup_owner && `backup: ${str(p.backup_owner)}`,
        p.clinician_reviewer && `clinician reviewer: ${str(p.clinician_reviewer)}`].filter(Boolean).join(", ") + ".";
    case "state_changed": {
      const extra = [p.reason && `Reason: ${str(p.reason)}`, p.note && `Note: ${str(p.note)}`].filter(Boolean).join(" ");
      const appt = p.appointment as { date?: string; clinic?: string; site?: string } | undefined;
      const when = appt?.date ? ` Appointment ${appt.date}${appt.clinic || appt.site ? ` at ${appt.clinic ?? appt.site}` : ""}.` : "";
      return `${label(STATE_LABELS, str(p.from))} → ${label(STATE_LABELS, str(p.to))}.${when}${extra ? ` ${extra}` : ""}`;
    }
    case "contact_attempt":
      return `${words(label(CHANNEL_LABELS, str(p.channel)))}: ${label(CONTACT_RESULT_LABELS, str(p.result)).toLowerCase()}.`;
    case "notification_status":
      return `${words(str(p.template_id))} ${str(p.status)} by ${label(CHANNEL_LABELS, str(p.channel))} in ${label(LANGUAGE_LABELS, str(p.language))} (simulated, approved template v${str(p.template_version)}).`;
    case "red_flag_reported":
      return `Red flag: ${RED_FLAG_CODES[str(p.code)] ?? words(str(p.code)).toLowerCase()} (reported by ${str(p.source)}). Automation stopped.`;
    case "automation_resumed":
      return `Automation turned back on. Reason: ${str(p.reason)}`;
    case "note_added":
      return str(p.text);
    case "case_closed": {
      const ev = p.evidence as { visit_date: string; facility: string; record_number: string } | null | undefined;
      const proof = ev ? `Evidence: visit ${ev.visit_date} at ${ev.facility}, record ${ev.record_number}.`
        : p.signed_off_by ? `Signed off by ${str(p.signed_off_by)}.` : p.evidence_ref ? `Evidence: ${str(p.evidence_ref)}.` : "";
      return `Closed: ${str(p.closure_reason)}. ${proof}`;
    }
    case "barrier_reported":
      return `Barrier: ${label(BARRIER_LABELS, str(p.barrier))}.`;
    case "barrier_resolved":
      return `Barrier resolved: ${label(BARRIER_LABELS, str(p.barrier))}. ${str(p.resolution)}`;
    case "priority_overridden":
      return p.tier ? `Priority set to ${words(str(p.tier))} (${label(OVERRIDE_REASON_LABELS, str(p.reason))}): ${str(p.note)}`
        : `Priority override cleared (${label(OVERRIDE_REASON_LABELS, str(p.reason))}): ${str(p.note)}`;
    case "ladder_step":
      return `Day ${str(p.day)}: ${str(p.action)}.`;
    case "ai_draft_created":
      return p.verified ? `Call guide drafted; all ${str(p.checked_count)} numbers and dates checked.`
        : "Call guide drafted but withheld: it mentioned facts not in the record.";
    case "ai_draft_decision":
      return `Call guide ${p.decision === "use" ? "used" : "discarded"}.`;
    case "contact_revealed":
      return `Showed the patient's ${(p.fields as string[] | undefined)?.join(" and ") ?? "contact details"} to staff.`;
    default:
      return words(e.type);
  }
}
