# LoopCloser evaluation (labeled synthetic set)

**What this measures:** whether the running backend follows its own published rules (pathway routing, follow-up
priority points, guard rules, escalation). **What it does not measure:** clinical accuracy or patient outcomes.
No clinician has reviewed the labels or the pathways, and all cases are fictional.

- Scenarios: [`eval/scenarios.json`](eval/scenarios.json), 55 hand-labeled fictional cases. Labels were written
  from the README priority table, the pathway JSON triggers and [docs/guard-rules.md](docs/guard-rules.md).
  The same team wrote the code and the labels, so this is a conformance test, not an independent audit.
- Runner: [`eval/run_eval.py`](eval/run_eval.py). It drives the real FastAPI app over HTTP (TestClient, demo
  role headers, in-memory store). It never calls Gemini and never writes to Google Cloud.
- Run it: `make eval` (or `cd api && .venv/bin/python ../eval/run_eval.py`). Exit code 1 if any case fails.

## Results (run 2026-11-09, about 11:30 PM Manila time, commit on branch `finalist-polish`)

| Category | Cases | Correct | False positives | False negatives |
|---|---|---|---|---|
| Pathway routing, urgency and red flag at intake | 13 | 13 | 0 | 0 |
| Follow-up priority (tier and exact score) | 12 | 12 | 0 | 0 |
| Guard rules (allow or block, with the rule id where labeled) | 26 | 26 | 0 | 0 |
| Escalation after failed contacts | 4 | 4 | 0 | 0 |
| **Total** | **55** | **55** | **0** | **0** |

How false positives and negatives are counted:
- Routing: a false positive marks a case urgent or red-flagged when the label says it is not; a false negative
  misses one the label expects.
- Priority: a false positive puts a case in a higher tier than labeled (wasted staff time); a false negative puts
  it lower (the risky direction).
- Guards: a false positive blocks an action that should be allowed; a false negative allows an action that
  should be blocked.

**Does the eval catch mistakes?** Yes. As a check, we ran it once with two deliberate bugs injected in memory
(the "no successful contact" rule worth 1 point instead of 2, and closing without evidence allowed). It flagged
8 failures: 7 priority cases (3 of them under-prioritized) and the "close without evidence" guard. The code
was not changed for that check.

## Speed

| Where | What | Result |
|---|---|---|
| Local, in-process (no network) | 165 API requests across the eval | p50 4.5 ms, p95 5.8 ms |
| Live demo, from our test machine | `/health`, 5 requests | p50 321 ms (mostly network) |
| Live demo | Today view as supervisor (`/api/today`), 5 requests | p50 961 ms, p95 4.0 s (first call slower) |
| Live demo | One case detail, 5 requests | p50 352 ms, p95 615 ms |
| Live demo | **Cold start**: first request after the API scaled to zero | **10.2 s** (old image, Nov 9, 11:2x PM) and **6.9 s** (new image, Nov 10, 12:08 AM Manila; Cloud Run log confirms a new instance) |

Live timings were measured from our test machine, not from the Philippines, with read-only requests only
(`--live-latency`), so they include network distance. The API runs at min 0 instances to cost nothing at idle,
which is why the first request after a quiet period takes about 10 seconds.

## Cost per patient (estimate from measured operations)

A full case lifecycle (open, review, notify, understanding check, booking, visit, close with evidence) made
**14 Firestore writes and about 35 reads** in the eval (counted by wrapping the store, same calls as the
Firestore repository). At the Firestore list price shown for us-central1 ($0.09 per 100,000 writes, $0.03 per
100,000 reads, [Firestore pricing](https://cloud.google.com/firestore/pricing)) that is about **US$0.00002 per
patient**, or about US$0.02 per 1,000 patients, before the free daily quota (20,000 writes, 50,000 reads).
Our database is in asia-southeast1, which is priced somewhat higher than us-central1, so treat this as an
order of magnitude. Not included: Today-view reads by staff, Cloud Run compute, and any Gemini calls (none in
the judged flow).

## AI call guide ("Prepare for the call"), live on Vertex AI

Deployed 2026-11-09 (Manila). Model `gemini-3.8-flash`, Vertex AI location `global`, thinking level low.

| Measure | Result |
|---|---|
| Live drafts on the deployed demo (smoke test) | 2 of 2 verified, 0 withheld |
| Live drafts from our test machine before deploy | 4; 3 verified, 1 false alarm ("two" copied from the pathway text) that led to a fix in the checker; 2 of 2 verified after the fix |
| Latency per draft, deployed | 2.7 s and 3.6 s (model time); about 4 s end to end |
| Tokens per draft | 420 to 470 input, 160 to 200 output, 0 thinking |
| Cost per draft | about US$0.001 at Vertex list price (US$0.75 / US$3.75 per 1M input / output tokens through Dec 31, 2026) |
| Red-flag case | refused before any model call (rule AI-2) |
| Use, then a second decision | Use logged; second decision refused (rule AI-3); case state, owner, deadline and priority unchanged |

That is a handful of live calls, not a quality benchmark. The checker is tested offline with a mocked model
(`api/tests/test_ai_call_prep.py`): invented dates, phone numbers, counts and blood-pressure values are all
flagged, and an unverified draft cannot be used.

## Escalation ladder on vs off (targets written before the first run)

**Status: targets only. Committed before the comparison code was run, so the git history shows they were not
fitted to the results.** Results and any misses are added below this section after the run.

Question: on the same synthetic cohort, what does the escalation ladder change by Day 14, compared with the
same system with the ladder switched off?

Setup (fixed in advance):
- Cohort: the demo seed (`POST /api/demo/seed`, n=1000, seed=42), loaded into two separate in-memory stores
  through the real API. Same rows, same owners, same starting states. All SIMULATED.
- Ladder on: the default ladder (Day 1, 2, 4, 7, 10, 14). Ladder off: `LADDER_JSON` with only the Day 0
  upload step, so no step ever runs. Everything else is identical.
- The demo clock is advanced one day at a time for 14 days (`POST /api/demo/clock`), as a supervisor would
  in the demo. No simulated staff or patient actions happen in either arm: this isolates what the ladder
  itself does when nobody follows up, which is the failure LoopCloser is built for.
- Measured on Day 14, over cases that are still open.

Definitions:
- **Unowned:** no named owner. **Unaccountable:** no named owner *and* not escalated to a supervisor, so no
  person is responsible for it.
- **Overdue:** past its pathway deadline and the visit is not completed. **Silently overdue:** overdue, not
  booked, not escalated, and automation not paused by a red flag (a red-flag case already has a human task).

Targets:

| # | Measure at Day 14 (open cases) | Ladder off | Ladder on target |
|---|---|---|---|
| T1 | Unaccountable (no owner, not escalated) | report the count | **0** |
| T2 | Silently overdue | report the count | **0** |
| T3 | Unowned (no named owner) | report the count | same as off: the ladder escalates, it does not assign owners |
| T4 | Overdue | report the count | same as off: the ladder cannot make a patient attend, so we do not claim it reduces overdue cases without real data |
| T5 | Cases with a valid phone that got at least one reminder or contact | 0 | **at least 90%** |
| T6 | Red-flag cases touched by automation | 0 | **0** (rule RF-1) |

Also reported, no target: the supervisor's escalated queue size on Day 14 (workload the ladder creates).

## Not measured yet
- Real-world contact success, show rates or closure time. These need a pilot with real (consented) data.
- Usability with real health workers.
- AI draft quality at scale (how often drafts are withheld, how often staff press Use), and whether drafts
  save health workers time. Both need real users.
