import { describe, expect, it } from "vitest";
import { actorLabel, daysBetween, dueText, label, STATE_LABELS, summarySentence, words } from "./labels";

describe("labels", () => {
  it("shows overdue days, not raw dates", () => {
    expect(dueText(-32)).toBe("32 days overdue");
    expect(dueText(-1)).toBe("1 day overdue");
    expect(dueText(0)).toBe("Due today");
    expect(dueText(3)).toBe("Due in 3 days");
    expect(dueText(null)).toBe("No deadline set");
  });
  it("never shows system (system, system)", () => {
    expect(actorLabel({ id: "system", role: "system", kind: "system" })).toBe("Automatic (rules engine)");
    expect(actorLabel({ id: "automation", role: "system", kind: "automation" })).toBe("Automatic (escalation ladder)");
    expect(actorLabel({ id: "demo-coord-01", role: "coordinator", kind: "human" })).toBe("demo-coord-01 (coordinator)");
  });
  it("turns raw enum values into words", () => {
    expect(label(STATE_LABELS, "no_show")).toBe("Missed the appointment");
    expect(label(STATE_LABELS, "something_new")).toBe("Something new");
    expect(words("worsening_symptoms")).toBe("Worsening symptoms");
  });
  it("writes the Today summary as a sentence", () => {
    expect(summarySentence({ to_contact: 12, overdue: 5, lost_contact: 3, needs_review: 2 }))
      .toBe("12 to contact. 5 overdue. 3 lost contact. 2 need review (supervisor or red flag).");
  });
  it("counts days between dates", () => {
    expect(daysBetween("2026-11-01", "2026-11-14")).toBe(13);
  });
});
