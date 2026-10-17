# LoopCloser Google Cloud project

LoopCloser uses its **own** project, separate from InvoiceSentinel. The id is set once in
`deploy/project.env` (placeholder `loopcloser-bkdkubo`). Project ids are global, so if that id is taken
when we create it, pick another (e.g. `loopcloser-bkdkubo-2026`) and change only that file and `.firebaserc`.

Status (checked Oct 17, 2026): **not created yet.** No project, billing link or resources exist.

## What creating it takes
`deploy/create-project.sh` (dry run unless `CONFIRM=yes`):
1. `gcloud projects create loopcloser-bkdkubo --organization 834340325006` (mmocanaiii-org; the account
   has Project Creator there).
2. Link the billing account (`gcloud billing projects link`). **Required**: Cloud Run, Artifact Registry and
   Cloud Build need billing, and Firebase Hosting rewrites to Cloud Run need the Blaze plan.
3. `firebase projects:addfirebase` (Hosting site `https://loopcloser-bkdkubo.web.app`, Firebase Auth).
4. Create the secret `loopcloser-gemini-api-key` in Secret Manager.
5. Budget alert (US$5/month, alerts at 50/90/100%).

Then `deploy/deploy.sh`: enable APIs, service account, Firestore `(default)` database with PITR,
Artifact Registry, build, Cloud Run (min 0), Hosting and Firestore rules.

## Free tier notes
- **Firestore:** free quota (1 GiB stored, 50k reads, 20k writes, 20k deletes per day) applies only to the
  `(default)` database, one per project. That is why we use `(default)` in our own project instead of a
  named database. Seeding 1,000 synthetic patients is a few thousand writes, so reseeding many times a day
  could pass 20k writes.
- **Cloud Run** (request-based billing): 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests
  free per month, **pooled per billing account**. InvoiceSentinel runs on the same billing account with
  min-instances 1 until judging ends, so it likely uses up that pool and LoopCloser pays from the first
  request until InvoiceSentinel goes back to min 0.
- **Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Firebase Hosting, Firebase Auth**
  (email/Google sign-in) all have free allowances far above what a demo uses.
- PITR and scheduled backups are billed on storage; for a few MB of synthetic data that is cents.

## Rough monthly cost at min-instances 0
About **US$0 to 2 per month** at demo traffic (a few thousand requests). Scaling to zero means no idle
compute charge. Things that could raise it: a min-instances 1 setting for judging (about US$10 to 15 per
month for the API, judging from InvoiceSentinel), heavy reseeding, or Gemini usage (billed on the Gemini
API key's project, not this one). Check the live pricing pages before enabling, these are estimates.
