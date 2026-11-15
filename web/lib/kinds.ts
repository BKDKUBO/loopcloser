import type { CaseEvent } from "./types";

/** The three kinds of content on a case (also in every download). Mirrors content_kind() in the API. */
export type Kind = "fact" | "rule" | "ai";

export const KIND_LABELS: Record<Kind, string> = {
  fact: "Recorded fact",
  rule: "Rule result",
  ai: "AI-written",
};

export const KIND_HELP: Record<Kind, string> = {
  fact: "Data on file: uploaded or entered by a person.",
  rule: "Calculated by a fixed rule: pathway deadline, priority points, gates, ladder steps.",
  ai: "Drafted by Gemini for staff only. Never sent to patients and never changes the case.",
};

const API_KIND: Record<string, Kind> = { recorded_fact: "fact", rule_result: "rule", ai_written: "ai" };

export function kindFromApi(k: string): Kind {
  return API_KIND[k] ?? "fact";
}

export function eventKind(e: CaseEvent): Kind {
  if (e.type === "ai_draft_created") return "ai";
  if (e.type === "ladder_step" || e.actor.kind !== "human") return "rule";
  return "fact";
}
