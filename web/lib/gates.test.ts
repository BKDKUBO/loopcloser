import { describe, expect, it } from "vitest";
import { blockReason, blockingGates, gateCounts } from "./gates";
import { eventKind, kindFromApi } from "./kinds";
import type { CaseEvent, CaseView, Gate } from "./types";

const gate = (id: string, status: "pass" | "hold", blocks: string[] = [], missing: string | null = null): Gate =>
  ({ id, label: id === "consent" ? "Consent to contact" : id, status, detail: id, missing, blocks, rule_id: "GATE-1" });

const c = (gates: Gate[], state = "reviewed") => ({ id: "C-1", state, gates } as unknown as CaseView);

describe("gates", () => {
  it("blocks calls and SMS while consent is not recorded, but not a home visit", () => {
    const v = c([gate("consent", "hold", ["call", "sms"], "Record consent first."), gate("owner", "pass")]);
    expect(blockingGates(v, "call").map((g) => g.id)).toEqual(["consent"]);
    expect(blockingGates(v, "chw_visit")).toEqual([]);
    expect(blockReason(v, "sms")).toBe("On hold (rule GATE-1): consent to contact — Record consent first.");
    expect(gateCounts(v)).toEqual({ pass: 1, hold: 1 });
  });
  it("an owner hold warns but blocks nothing", () => {
    expect(blockReason(c([gate("owner", "hold", [], "Assign an owner.")]), "call")).toBeNull();
  });
  it("closed cases are never blocked", () => {
    expect(blockReason(c([gate("consent", "hold", ["call"])], "closed"), "call")).toBeNull();
  });
});

const ev = (type: string, kind: "human" | "system" | "automation"): CaseEvent =>
  ({ id: "x", seq: 1, type, at: "", actor: { id: "a", role: "worker", kind }, rule_id: null, payload: {} });

describe("content kinds", () => {
  it("labels AI drafts, rule steps and recorded facts", () => {
    expect(eventKind(ev("ai_draft_created", "human"))).toBe("ai");
    expect(eventKind(ev("ladder_step", "system"))).toBe("rule");
    expect(eventKind(ev("state_changed", "system"))).toBe("rule");
    expect(eventKind(ev("contact_attempt", "human"))).toBe("fact");
    expect(kindFromApi("ai_written")).toBe("ai");
  });
});
