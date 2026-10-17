import type { CaseView } from "./types";

export type Lane = "needs_action" | "overdue" | "waiting" | "completed";

export const LANE_LABELS: Record<Lane, string> = {
  needs_action: "Needs action",
  overdue: "Overdue",
  waiting: "Waiting for patient",
  completed: "Recently completed",
};

const WAITING = new Set(["patient_notified", "action_scheduled", "rescheduled"]);
const DONE = new Set(["closed", "visit_completed"]);

/** Staff Today view lanes (PLAN_FINAL.md section 10). Pure, so it is unit tested. */
export function laneFor(c: CaseView, today: string): Lane {
  if (DONE.has(c.state)) return "completed";
  if (c.due_date && c.due_date < today) return "overdue";
  if (WAITING.has(c.state) && !c.red_flag_open) return "waiting";
  return "needs_action";
}

export function groupByLane(cases: CaseView[], today: string): Record<Lane, CaseView[]> {
  const out: Record<Lane, CaseView[]> = { needs_action: [], overdue: [], waiting: [], completed: [] };
  for (const c of cases) out[laneFor(c, today)].push(c);
  return out;
}

export function humanState(s: string): string {
  const t = s.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}
