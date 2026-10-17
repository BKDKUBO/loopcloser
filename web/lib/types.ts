export type Role = "worker" | "coordinator" | "supervisor" | "program_manager" | "patient";

export const ROLES: { id: Role; label: string }[] = [
  { id: "worker", label: "Care worker" },
  { id: "coordinator", label: "Coordinator" },
  { id: "supervisor", label: "Supervisor" },
  { id: "program_manager", label: "Program manager" },
  { id: "patient", label: "Patient" },
];

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
  next_action: string | null;
  due_date: string | null;
  escalation_level: number;
  contact_attempts: number;
  automation_paused: boolean;
  red_flag_open: boolean;
  synthetic: boolean;
  data_label: string | null;
  updated_at: string | null;
  data_quality: string[];
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
