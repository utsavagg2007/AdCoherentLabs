#!/bin/sh
# One image, three processes (D2). $1 selects the entrypoint.
#
# Single-env design: the whole backend + engine read the repo-root .env
# (mounted at /repo/.env, provided to the container via compose `env_file`).
# That file holds HOST endpoints (127.0.0.1) for host runs. Inside the compose
# network the stack is reachable by service name, so when APP_IN_CONTAINER=1 we
# rebuild the data-plane URLs from the secrets in that same env file — no second
# env file, no compose ${...} interpolation. This also sets DATABASE_URL, which
# the engine's RAG layer needs (host loopback is wrong inside a container).
#
# APP_IN_CONTAINER=1 means "I am on the local compose network, next to the
# redis and clamav SIDECARS" — not merely "I am in a container". A host that
# runs this same image WITHOUT those sidecars must NOT set it: there is no
# `redis` or `clamav` name to resolve, and rewriting the URLs to those names
# would break both.
set -e
cd /repo/backend

# --- cloud-mode safety guard: runs everywhere, sidecars or not --------------
# Deliberately outside the APP_IN_CONTAINER block below. A half-edited .env is
# the dangerous case — the process comes up pointing at a local stack (or at
# nothing) while every operator believes it is on Cloud. The API re-checks this
# in config.py::require_boot_secrets, but the worker and scheduler do not build
# a FastAPI app, so without this they would start against the wrong database.
if [ "${SUPABASE_MODE:-local}" = "cloud" ]; then
  case "$SUPABASE_URL$SUPABASE_DB_URL$DATABASE_URL_API$DATABASE_URL_WORKER" in
    *__PROJECT_REF__*|*__PASTE_*|*__GENERATE_*)
      echo "FATAL: SUPABASE_MODE=cloud but the env still has unfilled placeholders." >&2
      echo "       Copy .env.example to .env and fill in the Supabase values." >&2
      exit 1 ;;
    *127.0.0.1*|*localhost*|*supabase-db*|*supabase-kong*)
      echo "FATAL: SUPABASE_MODE=cloud but a data-plane URL still points at a local host." >&2
      exit 1 ;;
  esac

  # The engine's RAG store reads DATABASE_URL specifically, while the backend
  # reads DATABASE_URL_API/_WORKER. If the env set only SUPABASE_DB_URL the RAG
  # layer would get "" and retrieval would come back EMPTY rather than erroring
  # — a silent quality failure, not a crash. Align it for host and compose
  # alike (this used to live in the APP_IN_CONTAINER block, which any run
  # without the sidecars never reaches).
  export DATABASE_URL="${DATABASE_URL:-$SUPABASE_DB_URL}"
fi

if [ "${APP_IN_CONTAINER:-}" = "1" ]; then
  : "${REDIS_HOST:=redis}";  : "${REDIS_PORT:=6379}"
  : "${CLAMAV_SERVICE_HOST:=clamav}"

  # --- local sidecars: ALWAYS rewritten, in every mode -------------------
  # redis and clamav are compose services on this network regardless of where
  # Supabase lives, so their host-loopback values are always wrong in-container.
  export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0"
  # The root .env carries CLAMAV_HOST=127.0.0.1 for HOST runs, so a
  # "${CLAMAV_HOST:-clamav}" fallback would never fire and every containerised
  # upload would fail closed with 503 scanner_unavailable. Override it the same
  # way the URLs above are overridden; CLAMAV_SERVICE_HOST is the escape hatch.
  export CLAMAV_HOST="${CLAMAV_SERVICE_HOST}"

  # --- data plane: ONLY rewritten for the self-hosted stack --------------
  # With SUPABASE_MODE=cloud the .env holds real, reachable cloud URLs and
  # rewriting them to supabase-db/supabase-kong would point every container at
  # a stack that isn't on this network (or, worse, at a stale local one).
  if [ "${SUPABASE_MODE:-local}" != "cloud" ]; then
    : "${SUPABASE_DB_HOST:=supabase-db}"; : "${SUPABASE_DB_PORT:=5432}"
    : "${KONG_HOST:=supabase-kong}";      : "${KONG_PORT:=8000}"
    _db="postgresql://postgres:${POSTGRES_PASSWORD}@${SUPABASE_DB_HOST}:${SUPABASE_DB_PORT}/postgres"
    export SUPABASE_URL="http://${KONG_HOST}:${KONG_PORT}"
    export SUPABASE_DB_URL="$_db"
    export DATABASE_URL="$_db"           # engine RAG store (adcoherent_rag.config)
    export DATABASE_URL_API="$_db"
    export DATABASE_URL_WORKER="$_db"
    export DATABASE_URL_MIGRATIONS="$_db"
  fi
  # (cloud mode needs no data-plane rewrite here — the URLs in the env are
  #  already the real, reachable ones, and the guard at the top has vetted them)
fi

case "$1" in
  api)
    # $PORT wins where the platform ASSIGNS a port and routes traffic only
    # there — a container that binds anything else fails its start probe with
    # "the user-provided container failed to listen on $PORT". API_PORT stays
    # as the compose/host default, which is what the VM deploy uses.
    #
    # Workers: 2 suits a compose box. On a 1-vCPU host a second worker just
    # doubles the memory for the model imports — set UVICORN_WORKERS=1 there.
    # It is an env var rather than a hardcode so the same image serves both
    # without a rebuild.
    exec uvicorn app.main:app --host 0.0.0.0 \
         --port "${PORT:-${API_PORT:-8080}}" \
         --workers "${UVICORN_WORKERS:-2}"
    ;;
  worker)
    exec python -m worker.main
    ;;
  scheduler)
    exec python -m scheduler.main
    ;;
  *)
    exec "$@"
    ;;
esac
