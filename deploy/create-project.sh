#!/usr/bin/env bash
# One-time setup of LoopCloser's own Google Cloud + Firebase project.
# Already run once on Oct 17, 2026 for loopcloser-bkdkubo. Kept for re-creating the setup. Dry run by default. Linking billing is needed for Cloud Run.
# Run only after approval: CONFIRM=yes BILLING_ACCOUNT=XXXXXX-XXXXXX-XXXXXX deploy/create-project.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"

if [ "${CONFIRM:-}" != "yes" ]; then
  cat <<PLAN
Dry run. This would:
  1. Create project ${PROJECT_ID} under organization ${ORG_ID}
  2. Link billing account \${BILLING_ACCOUNT} (required for Cloud Run, Artifact Registry, Cloud Build)
  3. Add Firebase to the project (Hosting site https://${PROJECT_ID}.web.app, Firebase Auth)
  4. Create secret loopcloser-gemini-api-key (you paste the key; it never touches the repo)
  5. Set a budget alert on the billing account (e.g. US\$5/month, alerts at 50/90/100%)
Then run deploy/deploy.sh for the app itself.
Set CONFIRM=yes and BILLING_ACCOUNT to run.
PLAN
  exit 0
fi
: "${BILLING_ACCOUNT:?set BILLING_ACCOUNT}"

gcloud projects create "$PROJECT_ID" --organization "$ORG_ID" --name "LoopCloser"
gcloud billing projects link "$PROJECT_ID" --billing-account "$BILLING_ACCOUNT"
# firebase projects:addfirebase needs a Firebase CLI login; the REST call works with the gcloud login.
curl -sf -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "x-goog-user-project: $PROJECT_ID" \
  -H "content-type: application/json" -d '{}' "https://firebase.googleapis.com/v1beta1/projects/${PROJECT_ID}:addFirebase"
gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native --enable-pitr
gcloud firestore backups schedules create --database="(default)" --recurrence=daily --retention=14d
gcloud services enable secretmanager.googleapis.com billingbudgets.googleapis.com
echo "Paste the Gemini API key, then Ctrl-D:"
gcloud secrets create loopcloser-gemini-api-key --replication-policy automatic --data-file=-
gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" --display-name "LoopCloser" \
  --budget-amount 5USD --filter-projects "projects/${PROJECT_ID}" \
  --threshold-rule percent=0.5 --threshold-rule percent=0.9 --threshold-rule percent=1.0
echo "Project ${PROJECT_ID} ready. Next: CONFIRM=yes deploy/deploy.sh"
