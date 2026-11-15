# LoopCloser pitch deck: slide-by-slide draft

Updated 2026-11-15 to map the slides to the six official Future Health judging
parameters read out in the Hack2skill webinar on 4 November 2026. Every figure
below is copied from README.md and EVAL.md; do not add numbers that are not
there. The quote, demo video and pilot-partner slots stay as placeholders.

## 1. Cover
- LoopCloser
- "Every result has a next action, an owner, a deadline, and a documented outcome."
- Team BKD KUBO. Future Health Digital Innovation Challenge, Challenge 05: Closing the Screening-to-Care Loop
- Live demo: https://loopcloser-bkdkubo.web.app (Demo mode, no sign-in)

## 2. How judges can assess LoopCloser (criteria map)
- The six official parameters, with the slide that holds the evidence for each:
  1. Health impact and clinical relevance — slides 3–4
  2. Technical depth and architecture — slide 8
  3. Working solution and demonstration quality — slide 5
  4. Responsible AI, safety and data governance — slides 6–7
  5. Scalability and deployment readiness — slide 9
  6. Commercial viability and path to pilot — slide 10
- Assumptions and limitations: slide 11. Links and the video placeholder: slide 12.

## 3. The problem (criterion 1)
- Screening only helps if an abnormal result leads to care. In the Philippines that step is where people are lost.
- CLAMS (DOH-supported cervical screening, Metro Manila): only 43% returned after screening, though 94% of those who returned were treated (APAC Women's Cancer Coalition, May 2024).
- Santo Tomas, Laguna rural audit (2013 to 2017): 73% of women with an abnormal result never returned (35 of 48) (Journal of Global Health Reports).
- 34% of Filipino adults have hypertension; 49% of them did not know it; 48% controlled (PRESYON-5, 2026, PHA).
- We do not claim that LoopCloser has improved outcomes. There is no clinician sign-off and no pilot yet.
- Quote slot: TEAM TO SUPPLY a real nurse / BHW / patient quote with role and permission. Until then, the published Paranaque health worker quote from Balikas News Network may be used, clearly labeled as a published interview.

## 4. Who it is for (criterion 1)
- The nurse or coordinator at a rural health unit with a stack of abnormal results and no way to see who has been reached, booked or lost.
- LoopCloser gives each result an owner and a deadline, shows who to call first and why, and escalates automatically when nobody follows up.

## 5. Working solution (criterion 3)
- Live demo: https://loopcloser-bkdkubo.web.app (Demo mode, no sign-in). Thirteen scripted stories (C-DEMO-01 to C-DEMO-13); screenshots in docs/screenshots/v2/.
- Today view: four lanes (needs action, overdue, waiting for patient, recently completed), highest priority first.
- "Why this priority?": every rule that fired, with its points. Escalation ladder: reminder, then community health worker, then supervisor.
- Timeline: every change is an event with the person, role and the rule that allowed it.

## 6. The safety line (criterion 4)
- Rules decide (versioned, cited pathways; published points table; no ML in any decision).
- A human reviews each result before any patient contact. Automation can only escalate or ask for human review.
- People close (reason plus evidence or sign-off; API refuses otherwise, rules CLOSE-1 and CLOSE-3).
- Red flags stop automation until a person resolves them.
- AI only drafts, for staff. Not a diagnostic AI.
- Honest note: all pathways pending clinical sign-off; the team has no clinician yet.

## 7. Where AI helps (criterion 4)
- Gemini 3.8 Flash on Vertex AI drafts a short call guide from masked facts (no names, phones or notes).
- Every number and date is checked against the case record; unmatched drafts are withheld.
- Use / Discard are logged; drafts never change state, priority, owner or deadline.
- Live: 2.7 to 3.6 s per draft, about US$0.001 per draft.

## 8. Technical depth: measured, not estimated (criterion 2)
- 55 of 55 labeled synthetic cases correct, 0 false positives, 0 false negatives. Guard rules 26/26: 0 unsafe actions allowed, 0 safe actions blocked.
- A conformance test against our own rules, not clinical accuracy. The eval caught 8 failures when two bugs were deliberately injected.
- Event-sourced cases, versioned hash-locked pathways, a published priority table, and an escalation ladder. API tests: 142 passed, 3 skipped (they need the Firestore emulator).
- Ladder on vs off, 1,018 synthetic cases, Day 14 (targets written before the run): T1 unaccountable and T2 silently overdue both went to 0; T3 and T4 unchanged, as targeted.
- T5 missed: 70.1% of reachable patients contacted, against a 90% target. The supervisor queue grew from 1 case to 379 (one person, no cap).

## 9. Built on Google Cloud (criterion 5)
- Already live: Cloud Run (FastAPI, asia-southeast1), Firestore append-only event log, Firebase Hosting and Auth, Vertex AI (Gemini), Cloud Logging and Error Reporting.
- Default scale min 0, max 1 instance. Demo cost about US$0 to 2 per month; US$5 budget alert. About US$0.00002 database cost per patient lifecycle (14 writes, about 35 reads).
- Country setup (pathways, ladder days, message templates) is configuration, not code.
- Honest limits: only English and Filipino templates exist, and nothing has been tested outside the Philippines.

## 10. A path to a pilot (criterion 6)
- A 90-day pilot at one rural health unit: a proposal, not an agreement. Real patients only after clinical sign-off of the pathways and templates.
- TEAM TO CONFIRM any partner before naming one.
- Cost per facility per month at Google Cloud list prices: about US$0.34 at 100 abnormal results, about US$0.85 at 300. SMS is not included (sending is simulated; no provider is chosen yet).
- Who could pay, as options only: the LGU or RHU operating budget, or PhilHealth. No discussion has taken place with either.
- Optional next step: Model Armor screening of AI prompts and drafts.

## 11. Assumptions and limitations
- All demo cases are synthetic (1,000 generated patients plus 13 scripted stories, labeled SIMULATED). Fictional cases are accepted for this challenge; they are not clinical evidence.
- No clinical pilot and no clinician validation yet. Pathways are pending sign-off.
- Ladder comparison, Day 14, 1,018 synthetic cases: 70.1% of reachable patients contacted, against a 90% target (T5).
- The supervisor queue grows to 379 cases with the ladder on (1 with it off): one person, no cap. Overdue cases stayed at 355 in both arms.
- Dashboard and Today numbers come from demo data, not a real facility.
- SMS cost is not priced. Sending is simulated; no provider is chosen yet.
- A human reviews each result before any patient contact. If nobody reviews a result, the ladder makes it visible but does not message the patient.
- We do not claim improved outcomes. Fuller notes: docs/assumptions-and-limitations.md.

## 12. Team and links
- Team BKD KUBO
- Manuel III Ocaña, Product Lead & Solution Architect
- Elson Mojica, Domain Lead (Collections & Follow-up) & QA
- Live demo: https://loopcloser-bkdkubo.web.app
- GitHub: https://github.com/BKDKUBO/loopcloser
- Demo video link (TEAM TO ADD).
- Logo: the BKD KUBO mark (navy and teal kubo with the Philippine sun).
