import { describe, expect, it } from "vitest";
import { describeEvent } from "./timeline";
import type { CaseEvent } from "./types";

const ev = (type: string, payload: Record<string, unknown>): CaseEvent =>
  ({ id: "x", seq: 1, type, at: "2026-11-01T01:00:00Z", actor: { id: "system", role: "system", kind: "system" }, rule_id: null, payload });

describe("timeline", () => {
  it("describes status changes in words", () => {
    expect(describeEvent(ev("state_changed", { from: "reviewed", to: "escalated", reason: "Day 10: not booked yet" })))
      .toBe("Result reviewed → Escalated to supervisor. Reason: Day 10: not booked yet");
  });
  it("shows structured closure evidence", () => {
    expect(describeEvent(ev("case_closed", { closure_reason: "Colonoscopy done",
      evidence: { visit_date: "2026-11-11", facility: "District hospital", record_number: "DH-26-0417" } })))
      .toBe("Closed: Colonoscopy done. Evidence: visit 2026-11-11 at District hospital, record DH-26-0417.");
  });
  it("labels barriers and contact results", () => {
    expect(describeEvent(ev("barrier_reported", { barrier: "transport" }))).toBe("Barrier: Transport.");
    expect(describeEvent(ev("contact_attempt", { channel: "chw_visit", result: "reached" })))
      .toBe("Community health worker visit: reached.");
  });
  it("never prints the revealed values", () => {
    expect(describeEvent(ev("contact_revealed", { fields: ["name", "phone"] }))).toBe("Showed the patient's name and phone to staff.");
  });
});
