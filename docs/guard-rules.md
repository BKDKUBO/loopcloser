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
| CLOSE-1 | Closing needs a human, a reason, evidence **and** a sign-off (changed 2026-11-19; before, evidence *or* sign-off was enough). Evidence is the structured visit record, or for a declined or unreachable case a documented reference of at least 5 characters. Messages never close cases. |
| CLOSE-2 | Only a supervisor can sign off and close. The demo has no separate clinician role, so the supervisor is the clinical sign-off; coordinators prepare the evidence. |
| CLOSE-3 | Structured closure evidence needs a visit date (a real date, not in the future, not before the case opened), a facility (120 characters at most) and a record number (2 to 40 letters, digits, spaces, dots, dashes or slashes). The API still accepts a reference (`evidence_ref`, e.g. an upload id) as evidence; it never replaces the sign-off. |
| PRIV-1 | Names and phone numbers are never on the case or the Today view. A care worker, coordinator or supervisor can reveal them with a click; the reveal is an event (who, when, which fields, never the values). In this build only SIMULATED cases have contact details. |
| PRIV-2 | Downloading a case summary or audit trail is staff-only (no patient role) and is logged as a `case_exported` event (who, when, which download). Downloads mask the participant id and never contain names or phone numbers. |
| GATE-1 | Pass/hold gates on every case: consent to contact, contact details, result on file, owner assigned, no open red flag. Calls and SMS (manual and the Day 4 automated reminder) are blocked while consent is not recorded or there is no valid phone; every contact attempt, including a home visit, is blocked if the patient declined contact. Owner and red-flag gates warn. Consent is recorded by a human staff member with its source, never inferred by automation or AI. |
| MSG-3 | Official patient messages must use an approved template (id, version, language). No free text and no AI text. |
| MSG-4 | A patient SMS reply (YES, RESCHED or STOP; **simulated** in this build, entered on the mock phone page) is an event logged as the patient's phone, with the staff member who pressed it. YES moves a reviewed case to *Patient notified* at most (never *Understanding confirmed*, MSG-1) and marks a booked appointment confirmed. RESCHED moves a booked or missed visit to *Rescheduled*. STOP opts the patient out of SMS at once: manual SMS and the Day 4 reminder are blocked (an SMS opt-out hold appears). While a red flag is open a reply is only logged. Replies never book, close or clear a red flag. A reply needs an SMS to have been sent. |
| APPT-1 | Booking from the slot picker needs a slot that the **simulated** schedule offers (weekday, 09:00, 10:00, 11:00 or 14:00 Manila, the next 14 days). It goes through the normal transition guards (SM-1, OWN-1, RF-1). Booking after the pathway deadline is allowed and noted. The booking is stored on the case as a FHIR R4 `Appointment` resource and sent nowhere. |
| APPT-2 | A simulated slot holds 2 open booked cases at most, counted from LoopCloser's own case records. |
| RISK-* | Drop-off risk rules (`domain/risk.py`, `GET /api/risk/rules`): points for failed contacts, a missed visit, repeated rescheduling, open barriers, no valid phone, a reminder with nobody reached, a near or passed deadline without a booking, an appointment soon with a barrier. Watch at 3, high at 6. Read-time only: never changes the case, the priority tier or score, and never contacts anyone. Team-chosen, not validated; no percentages. |
| PRI-1 | Only a supervisor overrides follow-up priority, with a reason code and a note. The override is an event. |
| PRI-2 | Priority cannot be lowered, or an override cleared, while a red flag is open. |
| BAR-1 | Barriers come from a fixed list (transport, cost, work, language, digital, childcare, fear). Reporting and resolving each one is an event. |
| LAD-1 | Escalation ladder steps (Day 1, 2, 4, 7, 10, 14) run once each, skip paused or closed cases, skip steps no longer needed, and log an event. |
