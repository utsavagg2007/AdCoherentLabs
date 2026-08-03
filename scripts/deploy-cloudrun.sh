#!/usr/bin/env bash
# Deploy the AdCoherent containers to Cloud Run, behind Firebase Hosting.
#
#   bash scripts/deploy-cloudrun.sh api          # the FastAPI service
#   bash scripts/deploy-cloudrun.sh frontend     # the Next.js service
#   bash scripts/deploy-cloudrun.sh worker       # the queue worker
#   bash scripts/deploy-cloudrun.sh all
#
# Prerequisites, once per project — see DEPLOY_FIREBASE.md for the walkthrough:
#   gcloud auth login && gcloud config set project <id>
#   gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
#   gcloud artifacts repositories create adcoherent --repository-format=docker --location=$REGION
#   gcloud auth configure-docker $REGION-docker.pkg.dev
#   ...and the secrets created in Secret Manager (the script tells you which).
#
# Images are built LOCALLY and pushed, rather than `gcloud run deploy --source`,
# because the backend image needs `--target runtime` and the source-deploy path
# gives no way to select a build stage. Building the default (last) stage would
# ship `runtime` anyway, but only by accident — be explicit.

set -euo pipefail

# Check the tooling BEFORE anything else. Without this the first line below is
# `PROJECT=$(gcloud ... 2>/dev/null)`, and if gcloud is not installed `set -e`
# aborts on the failed substitution while the redirect swallows "command not
# found" — the script exits 127 having printed absolutely nothing.
for tool in gcloud docker; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "FATAL: '$tool' is not installed or not on PATH." >&2
    case "$tool" in
      gcloud) echo "       Install the Google Cloud CLI: https://cloud.google.com/sdk/docs/install" >&2 ;;
      docker) echo "       Install Docker Desktop and make sure it is running." >&2 ;;
    esac
    exit 1
  fi
done

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${GCP_REGION:-us-west1}"
REPO="${AR_REPO:-adcoherent}"
TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

if [ -z "$PROJECT" ] || [ "$PROJECT" = "(unset)" ]; then
  echo "FATAL: no GCP project. Run: gcloud config set project <project-id>" >&2
  exit 1
fi

# Non-secret configuration. Everything sensitive goes through Secret Manager
# below — env vars set this way are visible to anyone with viewer access on the
# service, and appear in `gcloud run services describe` output.
COMMON_ENV="APP_ENV=prod,SUPABASE_MODE=cloud,RETENTION_DRY_RUN=true"

# Secret Manager -> container env. Create each with, e.g.:
#   printf %s "$VALUE" | gcloud secrets create SUPABASE_DB_URL --data-file=-
# `printf %s` rather than `echo`: echo appends a newline, and a trailing \n in a
# database URL or JWT secret produces authentication failures that look nothing
# like the cause.
SECRETS="SUPABASE_DB_URL=SUPABASE_DB_URL:latest"
SECRETS="${SECRETS},DATABASE_URL_API=SUPABASE_DB_URL:latest"
SECRETS="${SECRETS},DATABASE_URL_WORKER=SUPABASE_DB_URL:latest"
SECRETS="${SECRETS},DATABASE_URL=SUPABASE_DB_URL:latest"
SECRETS="${SECRETS},SUPABASE_URL=SUPABASE_URL:latest"
SECRETS="${SECRETS},SUPABASE_JWT_SECRET=SUPABASE_JWT_SECRET:latest"
SECRETS="${SECRETS},SUPABASE_JWT_ISSUER=SUPABASE_JWT_ISSUER:latest"
SECRETS="${SECRETS},SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest"
SECRETS="${SECRETS},REDIS_URL=REDIS_URL:latest"
SECRETS="${SECRETS},OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest"
SECRETS="${SECRETS},ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"

build_and_push() {           # $1 = name, $2 = dockerfile, $3 = context, $4 = target
  local image="${REGISTRY}/$1:${TAG}"
  echo ">> building $image"
  if [ -n "${4:-}" ]; then
    docker build --target "$4" -f "$2" -t "$image" "$3"
  else
    docker build -f "$2" -t "$image" "$3"
  fi
  docker push "$image"
  echo "$image"
}

deploy_api() {
  local image; image=$(build_and_push adcoherent-api backend/Dockerfile . runtime | tail -1)
  gcloud run deploy adcoherent-api \
    --image="$image" --region="$REGION" --platform=managed \
    --set-env-vars="${COMMON_ENV},UVICORN_WORKERS=1,CLAMAV_REQUIRED=false" \
    --set-secrets="$SECRETS" \
    --cpu=2 --memory=4Gi \
    --min-instances=1 \
    --timeout=300 --concurrency=40 \
    --allow-unauthenticated
  # --min-instances=1: the image imports torch and PaddleOCR at startup. A cold
  #   start is tens of seconds, which the Firebase Hosting proxy would surface
  #   as a gateway timeout on the first request after idle.
  # --memory=4Gi: those same imports do not fit in the 512Mi default.
  # --allow-unauthenticated: the service is public because Firebase Hosting
  #   proxies to it; authentication is the app's own JWT layer, not IAM.
  # CLAMAV_REQUIRED=false: there is no clamd on Cloud Run. See the upload
  #   scanning section of DEPLOY_FIREBASE.md before using this in production —
  #   it makes uploads fail OPEN.
}

deploy_frontend() {
  # NEXT_PUBLIC_* are compiled in, so they are build args, not run-time env.
  # API_URL is same-origin because Firebase Hosting fronts both services.
  local image="${REGISTRY}/adcoherent-frontend:${TAG}"
  echo ">> building $image"
  docker build \
    --build-arg NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:?export it first}" \
    --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:?export it first}" \
    --build-arg NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:?export the public site origin, e.g. https://my-app.web.app}" \
    -t "$image" frontend
  docker push "$image"
  gcloud run deploy adcoherent-frontend \
    --image="$image" --region="$REGION" --platform=managed \
    --cpu=1 --memory=512Mi --min-instances=0 \
    --allow-unauthenticated
}

deploy_worker() {
  local image; image=$(build_and_push adcoherent-api backend/Dockerfile . runtime | tail -1)
  gcloud run deploy adcoherent-worker \
    --image="$image" --region="$REGION" --platform=managed \
    --command=docker-entrypoint.sh --args=worker \
    --set-env-vars="${COMMON_ENV},CLAMAV_REQUIRED=false" \
    --set-secrets="$SECRETS" \
    --cpu=2 --memory=4Gi \
    --min-instances=1 --max-instances=3 \
    --no-cpu-throttling \
    --no-allow-unauthenticated
  # The worker POLLS the job queue; it is not request-driven. Cloud Run throttles
  # CPU to near zero between requests by default, which would stall the poll loop
  # indefinitely — hence --no-cpu-throttling with --min-instances=1. This is
  # billed as an always-on instance. A dedicated VM is cheaper if it stays busy;
  # see DEPLOY_FIREBASE.md.
}

case "${1:-}" in
  api)      deploy_api ;;
  frontend) deploy_frontend ;;
  worker)   deploy_worker ;;
  all)      deploy_api; deploy_worker; deploy_frontend ;;
  *)        echo "usage: $0 {api|frontend|worker|all}" >&2; exit 2 ;;
esac

echo
echo "Deployed at tag ${TAG}. Now point Firebase Hosting at it:"
echo "  1. replace __CLOUD_RUN_REGION__ with ${REGION} in firebase.json"
echo "  2. replace __FIREBASE_PROJECT_ID__ with ${PROJECT} in .firebaserc"
echo "  3. firebase deploy --only hosting"
