// The safety line, shown where judges and staff make decisions. Static text: it describes what the
// backend enforces (api/loopcloser/domain/commands.py, docs/guard-rules.md); it does not enforce anything itself.
// collapsed: shown as a one-line "Who decides what" toggle (case page), open on the sign-in page.
export function SafetyLine({ pathway, collapsed = false }: { pathway?: string; collapsed?: boolean }) {
  const list = (
      <ol>
        <li><strong>Rules decide</strong> the pathway, the deadline and the follow-up priority
          {pathway ? <> (this case: pathway {pathway}, pending clinical sign-off)</> : null}. Every rule that
          fired is listed with its points.</li>
        <li><strong>People act.</strong> Every status change in the timeline shows who made it and which rule
          allowed it. Automation can only escalate or ask for human review.</li>
        <li><strong>A coordinator or supervisor closes</strong> a case, with a reason and evidence or a
          sign-off. Nothing closes automatically.</li>
        <li><strong>Red flags stop automation</strong> until a person resolves them, and only a supervisor
          can turn it back on.</li>
        <li><strong>AI only drafts, for staff.</strong> The optional call guide is labeled, checked number by number
          against the record, logged, and never changes the case. Patient messages use approved templates only.</li>
      </ol>
  );
  if (collapsed) {
    return (
      <details className="card safety">
        <summary><strong>Who decides what</strong> <span className="muted">(rules decide, people act and close, AI only drafts)</span></summary>
        {list}
      </details>
    );
  }
  return (
    <section className="card safety" aria-labelledby="safety-h">
      <h2 id="safety-h">Who decides what</h2>
      {list}
    </section>
  );
}
