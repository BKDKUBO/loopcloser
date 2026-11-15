import type { CaseView, Gate } from "./types";

export type Channel = "call" | "sms" | "chw_visit";

/** Gates on Hold that block a patient-contact channel (rule GATE-1). The API enforces the same rule. */
export function blockingGates(c: CaseView, channel: Channel): Gate[] {
  if (c.state === "closed") return [];
  return (c.gates ?? []).filter((g) => g.status === "hold" && g.blocks.includes(channel));
}

/** One sentence for a disabled button, or null when the channel is open. */
export function blockReason(c: CaseView, channel: Channel): string | null {
  const held = blockingGates(c, channel);
  if (held.length === 0) return null;
  return `On hold (rule GATE-1): ${held.map((g) => `${g.label.toLowerCase()} — ${g.missing ?? g.detail}`).join(" ")}`;
}

export function gateCounts(c: CaseView): { pass: number; hold: number } {
  const g = c.gates ?? [];
  return { pass: g.filter((x) => x.status === "pass").length, hold: g.filter((x) => x.status === "hold").length };
}
