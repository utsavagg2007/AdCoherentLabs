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
set -e
cd /repo/backend

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
  else
    # engine RAG store reads DATABASE_URL; keep it aligned with the pooler URL
    # the rest of the app uses if the env only set SUPABASE_DB_URL.
    export DATABASE_URL="${DATABASE_URL:-$SUPABASE_DB_URL}"
    case "$SUPABASE_URL$SUPABASE_DB_URL" in
      *127.0.0.1*|*localhost*|*supabase-db*)
        echo "FATAL: SUPABASE_MODE=cloud but the data-plane URLs still point at a local host." >&2
        exit 1 ;;
      *__PROJECT_REF__*|*__PASTE_*)
        echo "FATAL: SUPABASE_MODE=cloud but .env still has unreplaced placeholders." >&2
        exit 1 ;;
    esac
  fi
fi

case "$1" in
  api)
    exec uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT:-8080}" --workers 2
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
