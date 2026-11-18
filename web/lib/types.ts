export type Role = "worker" | "coordinator" | "supervisor" | "program_manager" | "patient";

export const ROLES: { id: Role; label: string }[] = [
  { id: "worker", label: "Care worker" },
  { id: "coordinator", label: "Coordinator" },
  { id: "supervisor", label: "Supervisor" },
  { id: "program_manager", label: "Program manager" },
  { id: "patient", label: "Patient" },
];

export const DEMO_STAFF = ["demo-worker-01", "demo-worker-02", "demo-worker-03", "demo-coord-01", "demo-coord-02"];

export interface PriorityReason { rule_id: string; points: number; label: string; detail: string | null }

export interface Priority {
  score: number;
  tier: "urgent" | "high" | "moderate" | "routine";
  tier_label: string;
  computed_tier: string;
  guidance: string;
  reasons: PriorityReason[];
  override: { tier: string; reason: string; note: string; by: string; at: string } | null;
  explanation: string;
}

export interface RecommendedAction { label: string; kind: string; target: string | null }

export interface LadderStep { day: number; id: string; label: string; state: "done" | "due" | "upcoming" | "not needed" }

export interface Gate {
  id: string;
  label: string;
  status: "pass" | "hold";
  detail: string;
  missing: string | null;
  blocks: string[];
  rule_id: string;
}

export interface CaseView {
  id: string;
  participant_id: string;
  screening_type: string;
  severity: string;
  pathway_id: string;
  pathway_version: string;
  pathway_signoff_status: string;
  state: string;
  clinical_urgency: string;
  owner: string | null;
  backup_owner?: string | null;
  next_action: string | null;
  due_date: string | null;
  escalation_level: number;
  contact_attempts: number;
  automation_paused: boolean;
  red_flag_open: boolean;
  synthetic: boolean;
  data_label: string | null;
  updated_at: string | null;
  version?: number;
  data_quality: string[];
  language?: string;
  barriers_open?: string[];
  appointment?: { date?: string; clinic?: string; confirmed_by_patient?: string; slot_id?: string; time?: string;
    simulated?: boolean; fhir?: Record<string, unknown> } | null;
  ladder_steps?: string[];
  priority?: Priority;
  recommended_action?: RecommendedAction;
  ladder?: LadderStep[];
  day?: number;
  plain_status?: "to_contact" | "booked" | "needs_review" | "done";
  plain_status_label?: string;
  lost_contact?: boolean;
  days_to_due?: number | null;
  failed_contact_attempts?: number;
  closure_reason?: string | null;
  closure_evidence?: string | null;
  closure_evidence_detail?: { visit_date: string; facility: string; record_number: string } | null;
  signed_off_by?: string | null;
  contact_consent?: "yes" | "no" | null;
  phone_valid?: boolean;
  gates?: Gate[];
  gates_on_hold?: string[];
  sms_opt_out?: boolean;
  last_sms_reply?: { keyword: string; at: string } | null;
  source?: { kind: string; resource?: string; code?: string | null; display?: string | null; interpretation?: string;
    referral?: string; bundle_id?: string | null } | null;
}

export interface CaseEvent {
  id: string;
  seq: number;
  type: string;
  at: string;
  actor: { id: string; role: string; kind: string };
  rule_id: string | null;
  payload: Record<string, unknown>;
}

export interface RenderedMessage {
  template_id: string;
  template_version: string;
  language: string;
  status: string;
  review_note: string;
  parts: Record<string, string>;
  text: string;
}
