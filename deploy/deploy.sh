#!/usr/bin/env bash
# Deploy LoopCloser: API to Cloud Run, web + Firestore rules/indexes to Firebase.
# NOT run yet. It creates billable resources (Artifact Registry, Cloud Run, Firestore).
# Run only after the team approves, with: CONFIRM=yes PROJECT_ID=... deploy/deploy.sh
set -euo pipefail
: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-southeast1}"
REPO="${REPO:-loopcloser}"
SA="loopcloser-api@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${TAG}"

if [ "${CONFIRM:-}" != "yes" ]; then
  cat <<PLAN
Dry run. This would:
  1. Enable run, artifactregistry, cloudbuild, firestore, secretmanager APIs in ${PROJECT_ID}
  2. Create service account ${SA} with roles/datastore.user
  3. Create Firestore database "loopcloser" (${REGION}) with point-in-time recovery
  4. Create Artifact Registry repo ${REPO} and build ${IMAGE}
  5. Grant ${SA} access to secret loopcloser-gemini-api-key (must already exist)
  6. Deploy Cloud Run service loopcloser-api (min 0, max 5 instances)
  7. Build the static web app and deploy Firebase Hosting site "loopcloser" + Firestore rules/indexes
Set CONFIRM=yes to run.
PLAN
  exit 0
fi

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create loopcloser-api --display-name "LoopCloser API"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" \
  --role roles/datastore.user --condition=None --format=none
gcloud firestore databases describe --database=loopcloser >/dev/null 2>&1 || \
  gcloud firestore databases create --database=loopcloser --location="$REGION" --type=firestore-native \
    --enable-pitr
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
gcloud secrets add-iam-policy-binding loopcloser-gemini-api-key \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --format=none

gcloud builds submit "$ROOT" --region "$REGION" --config "$ROOT/deploy/cloudbuild-api.yaml" \
  --substitutions "_IMAGE=${IMAGE}"
PROJECT_ID="$PROJECT_ID" IMAGE="$IMAGE" envsubst < "$ROOT/deploy/api-service.yaml" > /tmp/loopcloser-api.yaml
gcloud run services replace /tmp/loopcloser-api.yaml --region "$REGION"
gcloud run services add-iam-policy-binding loopcloser-api --region "$REGION" \
  --member allUsers --role roles/run.invoker --format=none   # public; the app enforces auth per route

(cd "$ROOT/web" && npm ci && NEXT_PUBLIC_API_URL="" NEXT_PUBLIC_AUTH_MODE="${WEB_AUTH_MODE:-firebase}" npm run build)
(cd "$ROOT" && firebase deploy --project "$PROJECT_ID" --only hosting,firestore)
echo "Done. Check: https://loopcloser.web.app/ready"
