#!/usr/bin/env bash
# Deploy LoopCloser: API to Cloud Run, web + Firestore rules/indexes to Firebase.
# NOT run yet. It creates billable resources (Artifact Registry, Cloud Run, Firestore).
# Project comes from deploy/project.env (override with PROJECT_ID=...). Needs deploy/create-project.sh first.
# Run only after the team approves, with: CONFIRM=yes deploy/deploy.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
REPO="${REPO:-loopcloser}"
SA="loopcloser-api@${PROJECT_ID}.iam.gserviceaccount.com"
TAG="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/api:${TAG}"

if [ "${CONFIRM:-}" != "yes" ]; then
  cat <<PLAN
Dry run. This would:
  1. Enable run, artifactregistry, cloudbuild, firestore, secretmanager APIs in ${PROJECT_ID}
  2. Create service account ${SA} with roles/datastore.user
  3. Create the Firestore (default) database (${REGION}) with point-in-time recovery
  4. Create Artifact Registry repo ${REPO} and build ${IMAGE}
  5. Grant ${SA} access to secret loopcloser-gemini-api-key (must already exist)
  6. Deploy Cloud Run service loopcloser-api (min 0, max ${MAX_INSTANCES} instances, DEMO_MODE=${DEMO_MODE})
  7. Build the static web app and deploy Firebase Hosting (${WEB_ORIGIN}) + Firestore rules/indexes
Set CONFIRM=yes to run.
PLAN
  exit 0
fi

# Firebase web config is public (it identifies the project, it is not a secret). Get it once with
#   firebase apps:sdkconfig WEB --project "$PROJECT_ID"
# and export NEXT_PUBLIC_FIREBASE_API_KEY / _AUTH_DOMAIN / _PROJECT_ID before running this script.
if [[ -z "${NEXT_PUBLIC_FIREBASE_API_KEY:-}" ]]; then
  echo "NEXT_PUBLIC_FIREBASE_API_KEY is not set: the web app would have no real sign-in. Stopping." >&2; exit 1
fi
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  firestore.googleapis.com secretmanager.googleapis.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create loopcloser-api --display-name "LoopCloser API"
for i in 1 2 3 4 5 6; do   # a new service account takes a moment to be visible to IAM
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" \
    --role roles/datastore.user --condition=None --format=none && break
  [ "$i" = 6 ] && exit 1; sleep 10
done
gcloud firestore databases describe --database="(default)" >/dev/null 2>&1 || \
  gcloud firestore databases create --database="(default)" --location="$REGION" --type=firestore-native \
    --enable-pitr
gcloud artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
gcloud secrets add-iam-policy-binding loopcloser-gemini-api-key \
  --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor --format=none

# Builds run as their own small service account (new projects give the default one no rights).
BUILD_SA="loopcloser-build@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud iam service-accounts describe "$BUILD_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create loopcloser-build --display-name "LoopCloser Cloud Build"
for role in roles/logging.logWriter roles/artifactregistry.writer roles/storage.objectViewer; do
  for i in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$BUILD_SA" \
      --role "$role" --condition=None --format=none && break
    [ "$i" = 6 ] && exit 1; sleep 10
  done
done
gcloud builds submit "$ROOT" --region "$REGION" --config "$ROOT/deploy/cloudbuild-api.yaml" \
  --service-account "projects/${PROJECT_ID}/serviceAccounts/${BUILD_SA}" \
  --substitutions "_IMAGE=${IMAGE}"
PROJECT_ID="$PROJECT_ID" IMAGE="$IMAGE" WEB_ORIGIN="$WEB_ORIGIN" DEMO_MODE="$DEMO_MODE" MAX_INSTANCES="$MAX_INSTANCES" envsubst < "$ROOT/deploy/api-service.yaml" > /tmp/loopcloser-api.yaml
gcloud run services replace /tmp/loopcloser-api.yaml --region "$REGION"
gcloud run services add-iam-policy-binding loopcloser-api --region "$REGION" \
  --member allUsers --role roles/run.invoker --format=none   # public; the app enforces auth per route

(cd "$ROOT/web" && npm ci && NEXT_PUBLIC_API_URL="" npm run build)
(cd "$ROOT" && firebase deploy --project "$PROJECT_ID" --only hosting,firestore)
echo "Done. Check: ${WEB_ORIGIN}/ready"
