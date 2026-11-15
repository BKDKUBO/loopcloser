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
| CLOSE-3 | Structured closure evidence needs a visit date (a real date, not in the future, not before the case opened), a facility (120 characters at most) and a record number (2 to 40 letters, digits, spaces, dots, dashes or slashes). The API still accepts a legacy reference id (`evidence_ref`, e.g. an upload id) or a sign-off; the web app only offers the structured form. |
| PRIV-1 | Names and phone numbers are never on the case or the Today view. A care worker, coordinator or supervisor can reveal them with a click; the reveal is an event (who, when, which fields, never the values). In this build only SIMULATED cases have contact details. |
| PRIV-2 | Downloading a case summary or audit trail is staff-only (no patient role) and is logged as a `case_exported` event (who, when, which download). Downloads mask the participant id and never contain names or phone numbers. |
| GATE-1 | Pass/hold gates on every case: consent to contact, contact details, result on file, owner assigned, no open red flag. Calls and SMS (manual and the Day 4 automated reminder) are blocked while consent is not recorded or there is no valid phone; every contact attempt, including a home visit, is blocked if the patient declined contact. Owner and red-flag gates warn. Consent is recorded by a human staff member with its source, never inferred by automation or AI. |
| MSG-3 | Official patient messages must use an approved template (id, version, language). No free text and no AI text. |
| PRI-1 | Only a supervisor overrides follow-up priority, with a reason code and a note. The override is an event. |
| PRI-2 | Priority cannot be lowered, or an override cleared, while a red flag is open. |
| BAR-1 | Barriers come from a fixed list (transport, cost, work, language, digital, childcare, fear). Reporting and resolving each one is an event. |
| LAD-1 | Escalation ladder steps (Day 1, 2, 4, 7, 10, 14) run once each, skip paused or closed cases, skip steps no longer needed, and log an event. |
