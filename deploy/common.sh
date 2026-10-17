# Sourced by the deploy scripts. Loads deploy/project.env; env vars win over the file.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_saved_project="${PROJECT_ID:-}"; _saved_region="${REGION:-}"
# shellcheck disable=SC1091
source "$ROOT/deploy/project.env"
PROJECT_ID="${_saved_project:-$PROJECT_ID}"; REGION="${_saved_region:-$REGION}"
for bad in $FORBIDDEN_PROJECT_IDS; do
  if [ "$PROJECT_ID" = "$bad" ]; then
    echo "Refusing: $PROJECT_ID is the InvoiceSentinel project. LoopCloser uses its own project." >&2
    exit 1
  fi
done
# Scope every gcloud/firebase call to this project without changing the global gcloud config.
export CLOUDSDK_CORE_PROJECT="$PROJECT_ID"
WEB_ORIGIN="https://${PROJECT_ID}.web.app"
