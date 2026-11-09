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
| Live demo | **Cold start**: first request after the API scaled to zero | **about 10.2 s** (observed 2026-11-09) |

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

## Not measured yet
- Real-world contact success, show rates or closure time. These need a pilot with real (consented) data.
- Usability with real health workers.
- The Gemini summary endpoint (not part of the judged flow).
