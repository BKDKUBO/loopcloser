import { KIND_HELP, KIND_LABELS, type Kind } from "@/lib/kinds";

/** One consistent badge for the three kinds of content: recorded fact, rule result, AI-written. */
export function KindBadge({ kind }: { kind: Kind }) {
  return <span className={`kind kind-${kind}`} title={KIND_HELP[kind]}>{KIND_LABELS[kind]}</span>;
}

export function KindLegend() {
  return (
    <p className="legend small" aria-label="What the labels mean">
      <strong>Labels on this page:</strong>{" "}
      {(["fact", "rule", "ai"] as Kind[]).map((k) => (
        <span key={k} className="legend-item"><KindBadge kind={k} /> {KIND_HELP[k]}</span>
      ))}
    </p>
  );
}
