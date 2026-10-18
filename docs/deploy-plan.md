# Deploy plan

**Status: deployed on 2026-10-18 (Asia/Manila) with DEMO_MODE=true.**
Live site https://loopcloser-bkdkubo.web.app, API https://loopcloser-api-ejilcnpasq-as.a.run.app.
Created: Firebase web app "LoopCloser Web", service accounts `loopcloser-api` (Firestore user, one secret)
and `loopcloser-build` (log writer, Artifact Registry writer, storage object viewer), Artifact Registry repo
`loopcloser`, Cloud Run service `loopcloser-api` (min 0, max 1). 1,005 SIMULATED cases seeded.
Not done: Google sign-in provider (needs the Firebase console, see below), real account roles, scheduler job.
The web build uses `NEXT_PUBLIC_GOOGLE_SIGNIN=off` so the Google button stays disabled until the provider is on.

The original plan follows. The project `loopcloser-bkdkubo` already exists with billing, Firebase, the needed
APIs, Firestore `(default)` with backups, the Gemini key in Secret Manager and a US$5/month budget alert
(see `gcp-project.md`). The InvoiceSentinel project is never touched; the scripts refuse its id.

## Steps

1. **Firebase web app and sign-in (one time).**
   - Register a web app in the project (`firebase apps:create WEB loopcloser-web`) and read its public config
     (`firebase apps:sdkconfig WEB`). This config is not a secret.
   - Turn on the Google sign-in provider in Firebase Authentication. This may need one click in the Firebase
     console, because Google sign-in needs an OAuth consent screen.
   - Add `loopcloser-bkdkubo.web.app` to authorized domains (Firebase adds it by default).
2. **API on Cloud Run.** `CONFIRM=yes deploy/deploy.sh` does:
   - service account `loopcloser-api` with Firestore user and access to the one secret only;
   - Artifact Registry repo `loopcloser` and a Cloud Build image;
   - Cloud Run `loopcloser-api` in asia-southeast1: min 0, max 1 instance, 1 vCPU, 512 MiB, `DEMO_MODE=true`,
     key injected from Secret Manager;
   - static web build and Firebase Hosting deploy, plus Firestore rules and indexes. Hosting sends `/api/**`,
     `/health` and `/ready` to Cloud Run, so the browser talks to one origin.
3. **Roles for real accounts.** `api/scripts/set_role.py <email> <role>` sets the `role` custom claim for each
   team member (for example you as supervisor).
4. **Check.** Open `https://loopcloser-bkdkubo.web.app/ready`, sign in with Google, then try Demo mode, seed
   1,000 SIMULATED patients as supervisor, and advance the clock.
5. **Optional.** A Cloud Scheduler job that calls `POST /api/ladder/run` once a day (3 free jobs per billing
   account). Not needed for judging, because the demo clock runs the ladder.

## Cost note

| Item | Expected cost |
| --- | --- |
| Cloud Run at min 0, max 1 | US$0 to 2/month at demo traffic. The free monthly Cloud Run allowance is shared across the billing account, and InvoiceSentinel at min 1 instance probably uses most of it, so we may pay a little for each request. |
| Cold starts | First request after idle takes a few seconds. Keeping one warm instance (min 1) for judging week would cost roughly US$10 to 15/month extra. Not recommended unless judges see slow loads. |
| Firestore `(default)` | US$0. Free tier is 1 GiB and 50k reads / 20k writes per day. Seeding 1,000 patients is roughly 10k to 15k writes, so seed at most once a day. Advancing the clock adds a few hundred writes each time. |
| PITR and daily backups | Cents per month at this data size. |
| Artifact Registry | US$0. 0.5 GB free; we keep a few images. |
| Cloud Build | US$0 within the free build minutes. |
| Firebase Hosting and Auth | US$0 on the free tier. |
| Secret Manager | US$0 (a few versions and accesses). |

Expected total: **about US$0 to 2 per month**. The US$5 budget alert emails at 50%, 90% and 100%.

## Decisions before deploy

- Approve running `deploy/deploy.sh`.
- Keep `DEMO_MODE=true` on the judged site? Anyone with the link can then act as any demo role, including
  seeding data and advancing the demo clock. All records are fictional. Set it to false for a real pilot.
- Who gets real accounts and which roles.
- `CLINIC_PHONE` is a placeholder `(02) 0000-0000 (demo number)`.
- The demo clock lives in memory on the single instance. It resets to today when the instance restarts.
  That is fine for a demo; a pilot would store it in Firestore or drop it.
