# Assumptions and limitations

This is the fuller list that accompanies the short [Assumptions and limitations](../README.md#assumptions-and-limitations)
section in the README. It is the technical-documentation note the official submission pack asks for (working
prototype, demo video, and documentation including assumptions and limitations). Every figure below is copied
from this repo, mostly [EVAL.md](../EVAL.md), [README.md](../README.md) and [docs/assumptions.md](assumptions.md).
Nothing here is a clinical result.

## Demo data is synthetic

The demo seed loads 1,000 generated patients (`api/loopcloser/synth/generator.py`, seed 42) plus 14 hand-written
stories (`DEMO_STORIES`, C-DEMO-01 to C-DEMO-14). Every row is labeled **SIMULATED**. The stories are replayed
through the same commands the app uses (`synth/stories.py`), so their timelines are real events, not pasted
text, but the people are fictional. Injected failure rates (invalid phone, no-show, transport barrier and so
on) are team test settings, not statistics about any real population; the values are listed in
[assumptions.md](assumptions.md).

The official webinar said fictional cases are acceptable for this challenge. That does not make them evidence
of clinical benefit.

## No clinical pilot, and no clinician validation yet

No rural health unit has agreed to a pilot. The 90-day, one-facility pilot in the README is a proposal, not an
agreement. Pathways and patient-message templates are still labeled "pending clinical sign-off". Deadlines are
configurable defaults pending clinical review. Filipino templates are also pending native-speaker review. The
review template ([clinical-review.md](clinical-review.md)) and the printable question sheet
([submission/clinician-review-questions.md](../submission/clinician-review-questions.md)) have not been filled
in. The team has no clinician yet.

The labeled eval in [EVAL.md](../EVAL.md) is a conformance test: the same team wrote the published rules and
the 55 labels. It checks that the running API follows those rules (55 of 55 correct, 0 false positives, 0
false negatives). It does not measure clinical accuracy, contact success, show rates, closure time, or
usability with real health workers. We do not claim improved outcomes.

## Ladder comparison: T5 missed, and the supervisor queue floods

Targets were written down in commit `d908191` before the comparison was run. The latest run (2026-11-15,
`make eval`) used the demo seed in two in-memory stores, 1,000 generated patients plus the hand-made edge cases
and 14 scripted stories (1,019 cases opened; 1,017 still open on Day 14). The first run on 2026-11-14, with 13
stories, gave 625 of 892 (70.1%) for T5 and a queue of 379; story 14 is the only change. The demo clock was advanced one day at a
time for 14 days. No simulated staff or patient actions happened in either arm, on purpose: this measures only
what the ladder does when nobody follows up. All cases are SIMULATED. Full table: [EVAL.md](../EVAL.md).

| # | Measure at Day 14 (open cases) | Ladder off | Ladder on | Target | Met? |
|---|---|---|---|---|---|
| T1 | Unaccountable (no owner, not escalated) | 177 | 0 | 0 | yes |
| T2 | Silently overdue | 128 | 0 | 0 | yes |
| T3 | Unowned (no named owner) | 177 | 177 | same as off | yes |
| T4 | Overdue | 355 | 355 | same as off | yes |
| T5 | Cases with a valid phone that got at least one reminder or contact | 624 of 893 | 625 of 893 (70.0%) | at least 90% | **missed** |
| T6 | Red-flag cases touched by automation | 0 of 2 | 0 of 2 | 0 | yes |
| | Supervisor's escalated queue (no target) | 1 | 380 | | |

What the misses show, plainly (same points as EVAL.md):

- **T5 missed (70.0% against a 90% target).** The ladder added a contact for only one more patient than doing
  nothing. Of the 268 reachable patients still uncontacted on Day 14, 267 were results nobody ever reviewed
  (state *new result*); the other is C-DEMO-14, held on purpose because consent to contact was not recorded.
  The ladder escalated every one of the 267 to the supervisor, but its reminder step only runs for
  reviewed or notified cases, so no patient message went out. If no one reviews a result, the ladder makes it
  visible but does not reach the patient.
- **The "ladder off" target for T5 was also wrong.** We wrote 0, but 624 of 893 reachable patients already had
  a contact in the seeded history before Day 0. The comparison is still fair (same cohort in both arms), but
  the off-arm number we predicted was not.
- **The ladder creates a supervisor flood.** 380 open cases end up in the escalated queue on Day 14 (1 with
  the ladder off): one person, no cap. T1 and T2 are met by moving responsibility to that person, not by
  getting care done. At real volumes a supervisor could not work 380 cases. T4 confirms it: overdue cases are
  unchanged (355 in both arms).

Possible fixes listed in EVAL.md are not built: send the approved reminder to new results with a valid phone
once a deadline is near (that would need clinical sign-off, because the patient would hear about a result
before staff review it), and cap or batch supervisor escalations with a per-owner digest.

## Dashboard and Today numbers are demo data

Figures on `/dashboard` and the Today summary sentence (for example "377 to contact. 93 overdue...") come from
the seeded demo cohort and the 14 scripted stories, not from a real facility. Screenshots in
[docs/screenshots/v2/](screenshots/v2/) were taken from that same local `finalist-v2` build.

## SMS is simulated and not priced

Official patient messages use approved templates only, and sending is simulated. No SMS provider is chosen
yet. The per-facility Google Cloud math in the README (about US$0.34 at 100 abnormal results per month, about
US$0.85 at 300) does not include SMS. The README states that SMS would likely cost more than everything in
that table. Staff time, devices and data plans, a Cloud Scheduler job for the daily ladder run, and support
are also not included. The 100 and 300 result volumes, and several of the request-count inputs, are planning
assumptions, not measured traffic; the measured inputs are the 14 writes and about 35 reads per patient
lifecycle, and about US$0.001 per Gemini draft ([EVAL.md](../EVAL.md), [README.md](../README.md#pilot-and-cost)).

## A human reviews each result before any patient contact

This is a product rule, not a claim about a pilot. Ladder Day 1 is human review. The automatic reminder step
only runs for cases that have already been reviewed or notified. Automation and system actors can only
escalate or ask for human review (rule AUTO-1). A delivered message can move a case to *Patient notified* at
most, and never closes it (MSG-2, CLOSE-1). If nobody reviews a result, the patient is not contacted
automatically; the case is escalated so a supervisor can see it. That is also why T5 missed.

Pass/hold gates (rule GATE-1) add a second stop. Each case shows consent to contact, contact details, result on
file, owner assigned and no open red flag, each as Pass or Hold. Calls and SMS, including the automatic Day 4
reminder, are blocked while consent is not recorded or there is no valid phone; every contact attempt is
blocked if the patient declined contact. Consent is recorded by a staff member with its source, never
inferred. Limits: consent is a yes/no flag with a free-text source, not a signed consent form or a legal
review of Philippine Data Privacy Act consent requirements; all generated demo rows have consent set to yes
(SIMULATED), so the gate only holds C-DEMO-14 and real imports without a consent column.
Closing needs a reason, evidence and a supervisor's sign-off (CLOSE-1, CLOSE-2, CLOSE-3; since 2026-11-19 evidence
*and* sign-off, before evidence *or* sign-off). There is no separate clinician role in the demo: the supervisor stands
in as the clinical sign-off.

FHIR import, SMS replies, calls and booking (feedback-v3): FHIR R4 Bundles are pasted or loaded from a synthetic
sample, never fetched from an EHR or a FHIR server; patient SMS replies are simulated with buttons on the mock phone;
"Call on my phone" only opens the worker's own dialer; appointment slots are simulated (fictional clinics, fixed
times, 2 places each). The drop-off risk strip is a fixed rule table chosen by the team, not a validated prediction. Red flags pause all automation until a person resolves them (RF-1, RF-2).

## Other limits already stated in the repo

- The live site at https://loopcloser-bkdkubo.web.app still runs the earlier build until `finalist-v2` is
  merged and redeployed (which has not been approved). The 14-story demo path and the v2 screenshots describe
  this branch, run locally.
- Default Cloud Run scale is min 0, max 1, so the first request after a quiet period can take about 7 to 10
  seconds (measured cold starts in EVAL.md: 10.2 s and 6.9 s).
- Gemini 3.8 Flash is called on Vertex AI's `global` location, so draft requests may be processed outside
  Singapore. They contain only masked, fictional case facts. There is no Model Armor screening yet.
- The Google sign-in provider is not switched on yet; judges use Demo mode.
- Only English and Filipino template texts exist. Nothing has been tested outside the Philippines.
- There is no integration with any health record system. Malaffi, Oracle Health and Epic are named in the
  README roadmap only as possible future targets.
- Downloads (case summary, audit trail CSV and JSON) are staff-only and logged, and mask the participant id.
  Free-text notes and closure reasons are included as typed, so a real deployment would need a policy on what
  staff may write in them. The printable summary is the browser's Print or Save as PDF; no server-side PDF.
- Firestore case-list queries are still full scans (indexes are declared; moving off scans is still open).
- There is no load test with the synthetic cohort yet, and no uptime check or alert policy on `/ready`.
- The per-patient database cost of about US$0.00002 in EVAL.md used us-central1 list prices as an order of
  magnitude; the database is in asia-southeast1, which is priced somewhat higher. The pilot table uses
  asia-southeast1 list prices fetched on 2026-11-14.
- Two README placeholders are still open and must not be invented: which files, if any, were adapted from
  InvoiceSentinel, and a first-person note on how collections work shaped the queue and ladder.
