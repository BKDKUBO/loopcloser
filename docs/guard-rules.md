# Guard rules

Enforced in `api/loopcloser/domain/commands.py` and covered by `api/tests/test_state_machine.py`.
A blocked action returns HTTP 422 with the `rule_id`.

| Rule | What it enforces |
|---|---|
| SM-1 | A transition must be allowed by the state machine (`domain/states.py`). No skipping steps. |
| SM-2 | Exception states need their fields. *Unable to reach* needs a reason and an escalation date. |
| AUTO-1 | Automation and system actors can only escalate or request human review. |
| MSG-1 | Understanding is confirmed by the understanding check or by staff, never by a message. |
| MSG-2 | A delivered or opened message moves a case to *Patient notified* at most. |
| OWN-1 | Urgent cases need a human owner before moving past *Reviewed*. |
| RF-1 | A red flag stops automation at once and opens a human task. Automation cannot act while paused. |
| RF-2 | Only a human moves a case through the red-flag states. Only a supervisor resumes automation, and only after the flag is resolved. |
| ESC-1 | After N failed contact attempts (default 3, `ESCALATE_AFTER_FAILED_CONTACTS`), the case escalates. |
| CLOSE-1 | Closing needs a human, a reason, and evidence or a sign-off. Messages never close cases. |
| CLOSE-2 | Only a coordinator or supervisor can close or sign off. |
| MSG-3 | Official patient messages must use an approved template (id, version, language). No free text and no AI text. |
| PRI-1 | Only a supervisor overrides follow-up priority, with a reason code and a note. The override is an event. |
| PRI-2 | Priority cannot be lowered, or an override cleared, while a red flag is open. |
| BAR-1 | Barriers come from a fixed list (transport, cost, work, language, digital, childcare, fear). Reporting and resolving each one is an event. |
| LAD-1 | Escalation ladder steps (Day 1, 2, 4, 7, 10, 14) run once each, skip paused or closed cases, skip steps no longer needed, and log an event. |
