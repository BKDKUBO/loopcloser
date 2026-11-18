/** Readable labels for the API's enum values. Unknown values fall back to plain words. */

export function words(s: string): string {
  const t = s.replace(/[_-]+/g, " ").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : t;
}

export const STATE_LABELS: Record<string, string> = {
  new_result: "New result",
  reviewed: "Result reviewed",
  patient_notified: "Patient told the result",
  understanding_confirmed: "Patient understands the next step",
  action_scheduled: "Appointment booked",
  visit_completed: "Visit done",
  closed: "Closed",
  unable_to_reach: "Unable to reach",
  declined: "Patient declined",
  rescheduled: "Needs a new appointment",
  referral_rejected: "Referral not accepted",
  no_show: "Missed the appointment",
  awaiting_human_review: "Waiting for staff review",
  escalated: "Escalated to supervisor",
  red_flag_reported: "Red flag reported",
  automation_paused: "Automation paused",
  human_task_open: "Red flag: staff task open",
  clinician_contacted: "Clinician contacted",
  resolved_by_human: "Red flag resolved by staff",
};

export const EVENT_LABELS: Record<string, string> = {
  case_opened: "Case opened",
  owner_assigned: "Owner assigned",
  state_changed: "Status changed",
  contact_attempt: "Contact attempt",
  notification_status: "Message (simulated)",
  red_flag_reported: "Red flag reported",
  automation_resumed: "Automation resumed",
  note_added: "Note",
  case_closed: "Case closed",
  barrier_reported: "Barrier reported",
  barrier_resolved: "Barrier resolved",
  priority_overridden: "Priority overridden",
  ladder_step: "Escalation ladder",
  ai_draft_created: "AI call guide drafted",
  ai_draft_decision: "AI call guide decision",
  contact_revealed: "Name or phone shown to staff",
  consent_recorded: "Consent to contact recorded",
  case_exported: "Case summary or audit trail downloaded",
};

export const BARRIER_LABELS: Record<string, string> = {
  transport: "Transport", cost: "Cost", work: "Work hours", language: "Language", digital: "No phone or internet",
  childcare: "Childcare", fear: "Fear or worry",
};

export const OVERRIDE_REASON_LABELS: Record<string, string> = {
  duplicate: "Duplicate case",
  already_treated: "Already treated",
  worsening_symptoms: "Worsening symptoms",
  completed_elsewhere: "Care completed elsewhere",
  data_error: "Data error",
  clinical_judgment_documented: "Clinical judgment (documented)",
  other: "Other",
};

export const CONTACT_RESULT_LABELS: Record<string, string> = {
  reached: "Reached", no_answer: "No answer", invalid_number: "Invalid number", busy: "Busy",
  left_message: "Left a message",
};

export const CHANNEL_LABELS: Record<string, string> = {
  call: "phone call", sms: "SMS", chw_visit: "community health worker visit",
};

export const SCREENING_LABELS: Record<string, string> = {
  fit: "Stool test (FIT)", bp: "Blood pressure", cervical: "Cervical screen", generic: "Other result",
  symptom: "New symptoms",
};

export const ROLE_LABELS: Record<string, string> = {
  worker: "care worker", coordinator: "coordinator", supervisor: "supervisor", program_manager: "program manager",
  patient: "patient", system: "system",
};

export const LANGUAGE_LABELS: Record<string, string> = {
  en: "English", fil: "Filipino", ceb: "Cebuano", ilo: "Ilocano", hil: "Hiligaynon", war: "Waray",
  pam: "Kapampangan", bcl: "Bikol", ar: "Arabic",
};

export const RED_FLAG_CODES: Record<string, string> = {
  flagged_at_intake: "flagged at upload", new_symptoms: "new symptoms", severe_headache: "severe headache",
};

export const label = (map: Record<string, string>, v: string | null | undefined): string =>
  v ? map[v] ?? words(v) : "";

/** "Nena's case was changed by …": no more "system (system, system)". */
export function actorLabel(a: { id: string; role: string; kind: string }): string {
  if (a.kind === "automation") return "Automatic (escalation ladder)";
  if (a.kind === "system" || a.role === "system") return "Automatic (rules engine)";
  if (a.id === "demo-seed-history") return "Demo history (simulated)";
  if (a.id === "patient-sms (simulated)") return "Patient, by SMS (simulated)";
  return `${a.id} (${ROLE_LABELS[a.role] ?? words(a.role)})`;
}

/** "32 days overdue", "Due today", "Due in 3 days". days = due date minus today. */
export function dueText(days: number | null | undefined, closed = false): string {
  if (days === null || days === undefined) return "No deadline set";
  if (closed) return "Closed";
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  if (days === 0) return "Due today";
  return `Due in ${days} day${days === 1 ? "" : "s"}`;
}

/** Days between two ISO dates (b - a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000);
}

export function ownerLabel(owner: string | null | undefined): string {
  return owner ? owner : "No owner yet";
}

export interface Summary { to_contact: number; overdue: number; lost_contact: number; needs_review: number }

/** Today's one-line summary: "12 to contact. 5 overdue. 3 lost contact. 2 need review." */
export function summarySentence(s: Summary): string {
  return `${s.to_contact} to contact. ${s.overdue} overdue. ${s.lost_contact} lost contact. ${s.needs_review} need review (supervisor or red flag).`;
}
