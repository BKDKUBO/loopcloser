# LoopCloser against WHO AI-for-health guidance and DECIDE-AI

Two frameworks were named by the Inception 42 speaker in Hack2skill's Future Health webinar (4 November 2026,
around 36:01 and 50:42): WHO guidance on AI for health, and the "decision support system" reporting guideline
with "27 or 28 criteria", which matches **DECIDE-AI** (17 AI-specific items plus 10 generic items, 27 in all).
This page maps LoopCloser to both. The framework text was checked on 15 November 2026 against the sources below.

**Read this first.** LoopCloser is a care-continuity tool, not a diagnostic or treatment-recommendation system.
Rules decide; people act; the only AI is an optional call guide drafted for staff. A mapping table is not
compliance: nobody outside the team has assessed LoopCloser against either framework, and no clinical study
has been run. "Not yet" below means exactly that.

Sources:
- WHO, *Ethics and governance of artificial intelligence for health: WHO guidance* (28 June 2021):
  https://www.who.int/publications/i/item/9789240029200. The six principles are also listed in the ITU-T
  FG-AI4H deliverable that reproduces the guidance: https://www.itu.int/dms_pub/itu-t/opb/fg/T-FG-AI4H-2022-PDF-E.pdf
- Vasey B. et al., *Reporting guideline for the early-stage clinical evaluation of decision support systems
  driven by artificial intelligence: DECIDE-AI*, Nature Medicine 28, 924–933 (2022):
  https://www.nature.com/articles/s41591-022-01772-9 (checklist: Table 2,
  https://www.nature.com/articles/s41591-022-01772-9/tables/2)

## WHO: six principles for AI in health

| WHO principle | What it asks (short paraphrase of the guidance) | Where LoopCloser stands | Evidence in this repo |
|---|---|---|---|
| 1. Protect human autonomy | Humans stay in control of health-care systems and medical decisions; privacy, confidentiality and valid informed consent are protected. | Rules decide and people act; AI never changes a case. Closing needs a coordinator or supervisor. Consent to contact is a gate: no calls or SMS until it is recorded by a person (GATE-1). Names and phones are hidden until a logged reveal. | `docs/guard-rules.md` (AI-1 to AI-3, CLOSE-1 to CLOSE-3, GATE-1, PRIV-1, PRIV-2); `api/loopcloser/domain/gates.py`; demo case C-DEMO-14 |
| 2. Promote human well-being, safety and the public interest | AI should not harm people; safety, accuracy and efficacy requirements for well-defined uses; quality control in practice. | Red flags stop all automation until a person resolves them. AI drafts are checked number by number against the record and withheld if anything does not match. **Not yet:** clinical sign-off of pathways, any efficacy evidence. | `EVAL.md` (55 of 55 rule conformance, AI checker tests); `api/tests/test_ai_call_prep.py`; README "Assumptions and limitations" |
| 3. Ensure transparency, explainability and intelligibility | Understandable to developers, professionals, patients, users and regulators; information documented before design or deployment. | Every case page labels content as **Recorded fact**, **Rule result** or **AI-written**. Priority shows each rule and its points. The timeline shows who did what under which rule, and can be downloaded. Code is public. | Case page legend and badges (`web/components/Kind.tsx`); `docs/screenshots/v2/16-case-labels-and-gates.png`; README workflow diagram |
| 4. Foster responsibility and accountability | Used under suitable conditions by trained people; mechanisms for questioning and redress. | Every result has a named owner or is escalated to a supervisor; every action is an append-only event with actor and rule id; downloads are logged. **Not yet:** a named clinical governance owner or a redress process at a real facility. | Event log design (README "Architecture"); `api/loopcloser/domain/events.py`; audit trail export |
| 5. Ensure inclusiveness and equity | Accessible to the widest range of people irrespective of age, gender, ethnicity and other characteristics. | Patients whose language has no approved template get +1 priority and a navigator flag; patients with no valid phone get a community health worker visit instead of SMS. **Not yet:** subgroup results on real data; templates exist only in English and Filipino. | Priority rule PRI-LANGUAGE; ladder step "chw"; C-DEMO-09 and C-DEMO-10; README "Beyond the Philippines" |
| 6. Promote AI that is responsive and sustainable | Applications assessed during actual use against expectations; environmentally and operationally sustainable. | AI use is small and logged (one draft per request, tokens and latency recorded). The cost per facility is published. **Not yet:** assessment during actual use; that is what the pilot evidence plan is for. | `EVAL.md` (tokens, cost per draft); README "Pilot and cost"; [pilot-evidence-plan.md](pilot-evidence-plan.md) |

## DECIDE-AI: reporting items for an early-stage clinical evaluation

DECIDE-AI is a **reporting** guideline for early, small-scale *live clinical* evaluations of AI decision
support. LoopCloser has not had one, so most results items cannot be reported yet. The table shows, for each
AI-specific item (1 to 17), what we could report today from the prototype and what only a pilot would produce.
The 10 generic items (I to X: abstract, objectives, research governance, outcomes, analysis, patient
involvement, main results, subgroups, strengths and limitations, conflicts of interest) are standard study
reporting and would be written with the pilot report.

| # | DECIDE-AI item (theme) | What we can report now | Needs the pilot |
|---|---|---|---|
| 1 | Title | n/a until there is a study | Yes |
| 2a | Intended use: condition, problem, current practice, population | Abnormal screening results (FIT, blood pressure, cervical) at a rural health unit that are not followed up; README "The problem" (cited sources) | Confirm with the facility |
| 2b | Intended users, place in the care pathway, intended effect | Nurses, coordinators, community health workers, supervisors; call guide used before phoning a patient; README workflow diagram | Confirm with users |
| 3a–c | Patient and user recruitment, user training | None: no patients or users recruited | Yes |
| 4a | AI system, version, algorithm | Gemini `gemini-3.8-flash` on Vertex AI, prompt version logged on every draft; no model trained by us | Version used during the pilot |
| 4b | Inputs, how acquired, missing data | Masked case facts only (no names, phones or notes); missing consent or phone puts the case on Hold (GATE-1) | Real missingness rates |
| 4c | Outputs and how they are shown | "AI draft. Not medical advice." guide, labeled **AI-written**, withheld if any number or date does not match; screenshot 17 | Same |
| 5a–b | Setting; workflow, timing, who makes the final decision | Staff decide; the draft never changes the case (rule AI-1) | Real setting |
| 6a–b | How errors and safety risks are defined and handled | Unsupported numbers or dates in a draft are errors and the draft is withheld; red flags block drafts (AI-2) | Error log from real use |
| 7 | Human factors methods | Not done | Yes (usability method to be chosen) |
| 8 | Ethics methods (e.g. fairness) | WHO mapping above; language and phone-access rules | Subgroup analysis |
| 9a–b | Baseline characteristics of patients and users; input missingness | None | Yes |
| 10a–b | Exposure, adherence, workflow changes | Drafts, Use and Discard are logged per case, so this can be counted | Yes |
| 11 | Modifications during the study | Prompt and checker versions are in git history (e.g. call-prep prompt v2) | Yes |
| 12 | Human–computer agreement | Use and Discard decisions are logged, one per draft (AI-3) | Yes |
| 13a–b | Errors, malfunctions, harm observed | None observed because no real use | Yes |
| 14a–b | Usability evaluation; learning curves | Not done | Yes |
| 15 | Support for intended use | Cannot be claimed | Yes |
| 16 | Safety profile | Cannot be claimed beyond the design rules above | Yes |
| 17 | Data and code availability | Code is public: https://github.com/BKDKUBO/loopcloser. Demo data is synthetic and generated by the repo | Data-sharing terms for pilot data |

What follows from this: the prototype is built so a DECIDE-AI-style report is *possible* (versioned prompt,
logged drafts and decisions, labeled outputs, downloadable audit trail), but none of the results rows can be
filled until real staff use it. The plan for that is in [pilot-evidence-plan.md](pilot-evidence-plan.md).
