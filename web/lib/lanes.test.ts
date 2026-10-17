import { describe, expect, it } from "vitest";
import { groupByLane, humanState, laneFor } from "./lanes";
import type { CaseView } from "./types";

const base: CaseView = {
  id: "C-1", participant_id: "P-••••42", screening_type: "fit", severity: "abnormal",
  pathway_id: "fit-positive", pathway_version: "1.0.0", pathway_signoff_status: "pending_clinical_signoff",
  state: "new_result", clinical_urgency: "standard", owner: "w", next_action: "x", due_date: "2026-11-01",
  escalation_level: 0, contact_attempts: 0, automation_paused: false, red_flag_open: false,
  synthetic: true, data_label: "SIMULATED", updated_at: null, data_quality: [],
};

describe("lanes", () => {
  it("puts overdue open cases in Overdue", () => {
    expect(laneFor({ ...base, due_date: "2026-10-01" }, "2026-10-17")).toBe("overdue");
  });
  it("red flags always need action", () => {
    expect(laneFor({ ...base, state: "patient_notified", red_flag_open: true }, "2026-10-17")).toBe("needs_action");
  });
  it("groups", () => {
    const g = groupByLane([base, { ...base, id: "C-2", state: "closed" }], "2026-10-17");
    expect(g.needs_action).toHaveLength(1);
    expect(g.completed).toHaveLength(1);
  });
  it("labels states in words", () => {
    expect(humanState("patient_notified")).toBe("Patient notified");
  });
});
