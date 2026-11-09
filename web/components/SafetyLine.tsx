// The safety line, shown where judges and staff make decisions. Static text: it describes what the
// backend enforces (api/loopcloser/domain/commands.py, docs/guard-rules.md); it does not enforce anything itself.
export function SafetyLine({ pathway }: { pathway?: string }) {
  return (
    <section className="card safety" aria-labelledby="safety-h">
      <h2 id="safety-h">Who decides what</h2>
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
        <li><strong>AI never decides.</strong> No AI output is shown on this page. Patient messages use
          approved templates only.</li>
      </ol>
    </section>
  );
}
