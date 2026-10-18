# LoopCloser

**Every result has a next action, an owner, a deadline, and a documented outcome.**

Team BKD KUBO · Future Health Digital Innovation Challenge · Challenge 05: Closing the Screening-to-Care Loop.

LoopCloser is a care-continuity and safety system, **not a diagnostic AI**. An actionable screening result
opens a case. Each case has a named owner, a deadline from a versioned, cited pathway, and a next action.
Deterministic rules decide. Humans review, escalate and close. Gemini only drafts text
(explanations, translation of the unofficial help chat, staff summaries) and never decides urgency,
priority, pathway, closure or anything clinical.

> All pathways are **pending clinical sign-off**. All data is **SIMULATED** and fictional.

## Architecture

```
Browser (Next.js static export)
   │  Firebase Auth sign-in (ID token with custom claim "role")
   ▼
Firebase Hosting (CDN, cache headers, security headers)
   ├── static pages  ── cached at the edge
   └── /api/**, /health, /ready  ── rewrite ──►  Cloud Run: loopcloser-api (FastAPI)
                                                   │  verifies token, checks role permission,
                                                   │  rate limits, structured logs
                                                   ├── domain/commands.py  (guard rules)
                                                   ├── pathways/ (versioned JSON + LOCK.json)
                                                   ├── ai/assist.py (Gemini, draft text only)
                                                   ▼
                                     Firestore ((default) database)
                                       cases/{id}            projection (rebuildable)
                                       cases/{id}/events/{n} append-only event log (source of truth)
Secret Manager ──► GEMINI_API_KEY injected into Cloud Run at runtime
Cloud Logging / Error Reporting ◄── JSON logs with request ids and stack traces
```

Same stack as InvoiceSentinel (Next.js, FastAPI on Cloud Run, Firebase Hosting, Firestore, Gemini,
Secret Manager), but in **its own Google Cloud project** (`loopcloser-bkdkubo`, set once in
[deploy/project.env](deploy/project.env)). Nothing is shared with the InvoiceSentinel project, and the
deploy scripts and CI refuse its id. The web app is a static export served from the Hosting CDN, so it
costs nothing at idle and the API is same-origin. See [docs/gcp-project.md](docs/gcp-project.md) for
project setup, billing and cost.

### Core data model
- **Case state machine** (`api/loopcloser/domain/states.py`): main path *New result → Reviewed →
  Patient notified → Understanding confirmed → Action scheduled → Visit completed → Closed*, exception
  states (*Unable to reach, Declined, Rescheduled, Referral rejected, No-show, Awaiting human review,
  Escalated*) and red-flag states (*Red flag reported → Automation paused → Human task open →
  Clinician contacted / Resolved by human*).
- **Guard rules** (`domain/commands.py`, listed in [docs/guard-rules.md](docs/guard-rules.md)): messages
  never move a case past *Patient notified* and never close it; closing needs a coordinator or supervisor
  plus a reason and evidence or sign-off; urgent cases need a human owner; red flags pause automation and
  only a supervisor can resume it; N failed contacts escalate.
- **Single owner per case**: `owner`, `backup_owner`, `clinician_reviewer`, `next_action`, `due_date`,
  `escalation_level`, contact counters, `closure_reason`. Cases without an owner get a data-quality flag.
- **Append-only event log** (`domain/events.py`, `store/`): every action is an immutable event with actor,
  rule id and fields used. State is derived by folding events (`domain/case.py`). Appends use optimistic
  concurrency, and in Firestore `create()` so an event can never be overwritten. Clients cannot write at all.
- **Versioned pathway library** (`pathways/data/*.json`): abnormal (generic), borderline, positive FIT
  (colonoscopy, not a repeat FIT), elevated blood pressure (WHO: 140 and/or 90 mmHg on two days) as MUST;
  abnormal cervical and new symptoms as SHOULD. Each has sources and a "pending clinical sign-off" badge.
  Deadlines are "configurable default, pending clinical review". `LOCK.json` makes published versions
  immutable: changing one fails the tests, so changes need a new version.
- **Synthetic generator** (`synth/generator.py`): seeded, 1,000 fictional patients plus hand-made edge
  cases, every row labeled `SIMULATED`. Injected failure rates are team test settings, not statistics
  (see [docs/assumptions.md](docs/assumptions.md)).
- **CSV validation** (`imports/csv_validation.py`): row-level errors and warnings, import of valid rows only,
  downloadable error CSV.

## Week 2 features

- **Demo mode (judges).** With `DEMO_MODE=true` the sign-in page shows a "Demo mode: pick a role" card and every page
  shows a banner: production uses real Firebase Auth accounts with role permissions. Real sign-in stays available.
- **Follow-up priority (points, not AI).** Critical result +5, red flag +5, deadline passed +4, due within 3 days +3,
  no appointment +3, missed visit +2, transport/cost/work barrier +2, no successful contact +2, comorbidity +1,
  language support +1. Urgent 8+, High 5 to 7, Moderate 3 to 4, Routine 0 to 2. Every case shows a
  "Why this priority?" list. Supervisors can override with a reason and a note; the override is an event and cannot
  lower a case with an open red flag (`domain/priority.py`, rules PRI-1, PRI-2).
- **Today view.** Four lanes (needs action, overdue, waiting for patient, recently completed) sorted by priority,
  with Call, Message, Assign and the recommended action on each card.
- **Case detail action panel.** Next action with the reason, book, reschedule, escalate, close with evidence,
  barriers, escalation ladder status and the full event timeline.
- **Patient message templates.** Five templates in English and Filipino (result notice in 4 parts, reminder,
  short SMS, emergency guidance, booking confirmation), versioned and hash-locked. All are labeled
  **pending clinical and native Filipino speaker review**. Sending is simulated and template only. Gemini never
  sends official messages (rule MSG-3).
- **Escalation ladder.** Day 0 upload, Day 1 human review, Day 2 first contact, Day 4 reminder, Day 7 community
  health worker, Day 10 supervisor (case escalates), Day 14 unresolved review (`domain/ladder.py`, rule LAD-1).
  In demo mode a supervisor can advance a simulated clock to watch it run.

Screenshots: `docs/screenshots/week2/`. Deploy plan: `docs/deploy-plan.md`.

## Run locally

```
make install          # Python venv + npm packages
make api              # API on :8080, DEMO_MODE=true, in-memory store
make web              # web on :3000 (another terminal)
make seed             # load 1,000 SIMULATED patients
make test             # API + web unit tests
make test-emulator    # Firestore rules + Firestore repository tests (needs Java 21 and firebase-tools)
```

Open http://localhost:3000 and pick a role from the Demo mode card (or sign in with Google when Firebase is configured). API docs at http://localhost:8080/docs (off in production).

## Production-readiness checklist

Status: ✅ done in code and tested · 🟡 configured, applied at deploy · ⬜ next

### 1. Security
- ✅ Firebase Auth sign-in; the API verifies ID tokens with the Admin SDK (`api/loopcloser/auth.py`)
- ✅ Five roles (worker, coordinator, supervisor, program manager, patient) with a permission matrix
  (`domain/roles.py`); every route declares the permission it needs; hidden cases return 404
- ✅ Domain guards repeat the critical checks (only coordinator/supervisor close, only supervisor resumes automation)
- ✅ Firestore security rules enforce roles: workers read only assigned cases, patients only their own case
  and never the event log, no client writes anywhere (`firestore.rules`, 8 emulator tests)
- ✅ API rate limiting: 120/min per IP, 10/min for imports, AI and demo seeding; `429` with `Retry-After`
- ✅ Secrets in Secret Manager only: Cloud Run injects `GEMINI_API_KEY` via `secretKeyRef`; production never
  reads `.env`; `.env` files are git-ignored; gitleaks runs in CI
- ✅ Demo mode is off by default and only turns on with `DEMO_MODE=true`. It adds a labeled role switcher on top of
  real Firebase Auth (a Bearer token always wins, demo users are forced to `demo-` ids). Production config refuses
  the memory store and wildcard CORS
- ✅ Participant ids masked for staff (`P-••••42`); logs carry ids only, never names or phones
- ✅ Gemini boundary test: the AI module cannot import commands, stores or pathways
- 🟡 Least-privilege service account `loopcloser-api` (Firestore user + one secret)
- ⬜ Real accounts and role assignment (`api/scripts/set_role.py`)

### 2. Shipping
- ✅ GitHub Actions CI: ruff lint and format, pytest, ESLint, TypeScript, vitest, Next build,
  Firestore emulator tests, secret scan (`.github/workflows/ci.yml`)
- 🟡 Deploy workflow, manual trigger, Workload Identity Federation (no JSON keys) (`deploy.yml`)
- 🟡 `deploy/create-project.sh` (one-time project setup) and `deploy/deploy.sh`, both dry run by default,
  plus `deploy/api-service.yaml`; project id in one file, `deploy/project.env`
- ✅ CI fails if the InvoiceSentinel project id appears anywhere
- ⬜ Create the project and first deploy (week 2, after approval)

### 3. Speed
- ✅ Static export served by the Firebase Hosting CDN; `/_next/static` cached for a year (immutable),
  other assets for a day, HTML revalidated every time
- ✅ API responses `Cache-Control: no-store` (case data is never cached)
- ⬜ Firestore queries with indexes once the case list moves off full scans (indexes already declared)

### 4. Traffic
- 🟡 Cloud Run autoscaling: min 0 instances (no idle cost), max 1 for the demo (MAX_INSTANCES in deploy/project.env), concurrency 80, startup CPU boost
- ✅ Health checks used as Cloud Run startup and liveness probes
- ⬜ Load test with the synthetic cohort before the demo; set min 1 only during judging

### 5. Survival
- ✅ Structured JSON logs for Cloud Logging with severity, request id, trace id and latency
- ✅ Error tracking: unhandled errors are logged with stack traces in Error Reporting format and the
  user gets a request id to quote
- ✅ `/health` (liveness) and `/ready` (storage, pathway lock, auth mode, AI mode)
- ✅ Projections can be checked against and rebuilt from the event log (`/api/admin/cases/{id}/verify-projection`)
- 🟡 Firestore point-in-time recovery and daily backups, with a restore drill ([docs/firestore-backup.md](docs/firestore-backup.md))
- ⬜ Uptime check and alert policy on `/ready` and on error rate

## What this is not
No diagnosis, no treatment advice, no autonomous triage, no ML risk scores, no LLM decisions,
no real SMS or patient data, no auto-closure, no claims of improved outcomes.

## Repo layout
```
api/            FastAPI app (loopcloser/), tests/, Dockerfile, scripts/set_role.py
web/            Next.js static app (Today view, case timeline, pathways, status)
firestore-tests/ security rules tests (emulator)
firestore.rules, firestore.indexes.json, firebase.json
deploy/         project.env, project setup + deploy scripts (dry run by default), Cloud Run service
docs/           guard rules, backup plan, simulation assumptions
```
