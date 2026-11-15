# Pilot evidence plan (a plan, not done)

> **Status: PLAN ONLY.** Nothing on this page has been carried out. No facility has agreed to a pilot, no
> clinician has reviewed LoopCloser, and no real patient data has been used. The numbers below are targets
> and definitions to agree with a clinician and a facility, not results.

The Inception 42 speaker in the 4 November 2026 webinar suggested starting validation by comparing a tool's
outputs against cases a clinician already knows (around 54:37 to 55:17). This plan applies that to LoopCloser, and
names the measures that a DECIDE-AI-style report would need ([frameworks.md](frameworks.md)).

## Step 1: retrospective check against cases a clinician already knows (before any live use)

- **Who:** one clinician (nurse or physician) from the partner facility, plus the facility's follow-up
  coordinator. Neither exists yet.
- **What:** 30 to 50 past abnormal results whose follow-up the clinician already knows (who was reached, who
  was lost, what the correct next step and deadline were), de-identified by the facility before anything leaves
  it, with written approval from the facility head and its data protection officer.
- **How:** load them through the CSV import (validation runs before anything is saved), then for each case
  record whether LoopCloser's **rule results** match the clinician's answer:
  - pathway and next action (correct or not),
  - deadline (the clinician's acceptable window, in days),
  - follow-up priority tier (would the clinician call this patient earlier or later),
  - gates (would the clinician have held contact for the same reason),
  - for any AI call guide drafted: anything the clinician would not want said to the patient.
- **Output:** a short agreement table per pathway, and a list of rules to change before Step 2. Pathways stay
  "pending clinical sign-off" until the clinician signs [clinical-review.md](clinical-review.md).

## Step 2: 90-day live pilot at one rural health unit (proposal in the README)

Run only after Step 1 and the clinician's sign-off. Compare against the facility's own records for the 90 days
before go-live (same screening types).

| Measure | Definition | Why it matters |
|---|---|---|
| Time to next action | days from result received to the first documented contact attempt | the core of "closing the loop" |
| Reached within the pathway deadline | share of abnormal results with a successful contact before the deadline | contact, not just activity |
| Completed follow-up | share with a recorded visit (structured evidence) within the deadline plus 30 days | the outcome the program wants |
| Lost to follow-up | share closed as unable to reach, or 3+ failed attempts and no success, at day 90 | the failure LoopCloser targets |
| Unowned or silently overdue | count each week (as in the ladder comparison, T1 and T2) | accountability |
| Supervisor queue size | open escalated cases each week | the known flood risk (EVAL.md) |
| Gate holds | cases on Hold by gate type, and days spent on Hold | missing consent or phone at intake |
| AI draft use | drafts requested, withheld by the checker, Used, Discarded | DECIDE-AI items 10 and 12 |
| AI draft errors | drafts with a statement the reviewer judged wrong or unsafe, even if the checker passed it | DECIDE-AI item 13 |
| Staff time | minutes per case for the coordinator, from a two-week time-and-motion sample before and during | whether it saves work |
| Usability | a standard short questionnaire (for example SUS) at day 30 and day 90 | DECIDE-AI item 14 |
| Subgroups | the contact and completion measures by language, age band and phone access | equity (WHO principle 5) |

Every measure except staff time and usability can be computed from the event log LoopCloser already keeps
(case opened, contact attempts, state changes, closures with evidence, AI draft events, gate holds).

## What would count as "not working"

To be agreed with the clinician before go-live, written down and committed before the data is looked at (as
the ladder targets were in commit `d908191`). Examples to discuss: no improvement in reached-within-deadline
over the baseline; any AI draft error that the clinician rates unsafe; a supervisor queue that stays above
what one person can review in a day.

## What this plan does not cover yet

Ethics review requirements at the facility, data sharing terms, SMS provider and its cost, and how the
facility's existing records would be exported. These are open questions for the first meeting with a partner.
