import type { Priority } from "@/lib/types";

export function PriorityBadge({ p }: { p?: Priority }) {
  if (!p) return null;
  return (
    <span className={`badge tier-${p.tier}`}>
      Follow-up priority: {p.tier_label} ({p.score}){p.override ? " · overridden" : ""}
    </span>
  );
}

export function WhyPriority({ p, open = false }: { p?: Priority; open?: boolean }) {
  if (!p) return null;
  return (
    <details open={open}>
      <summary>Why this priority?</summary>
      {p.reasons.length === 0 ? <p className="muted">No rules fired.</p> : (
        <ul>
          {p.reasons.map((r) => (
            <li key={r.rule_id}>{r.label} <strong>+{r.points}</strong>{r.detail ? ` (${r.detail})` : ""}
              <span className="muted"> · {r.rule_id}</span></li>
          ))}
        </ul>
      )}
      <p className="muted">{p.guidance}. Rules are fixed points, not AI. Total {p.score}: Urgent 8+, High 5 to 7,
        Moderate 3 to 4, Routine 0 to 2.</p>
      {p.override && (
        <p><strong>Override:</strong> {p.override.tier} by {p.override.by} ({p.override.reason}): {p.override.note}</p>
      )}
    </details>
  );
}
