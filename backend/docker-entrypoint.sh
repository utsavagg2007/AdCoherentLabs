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
  : "${SUPABASE_DB_HOST:=supabase-db}"; : "${SUPABASE_DB_PORT:=5432}"
  : "${REDIS_HOST:=redis}";             : "${REDIS_PORT:=6379}"
  : "${KONG_HOST:=supabase-kong}";      : "${KONG_PORT:=8000}"
  : "${CLAMAV_SERVICE_HOST:=clamav}"
  _db="postgresql://postgres:${POSTGRES_PASSWORD}@${SUPABASE_DB_HOST}:${SUPABASE_DB_PORT}/postgres"
  export SUPABASE_URL="http://${KONG_HOST}:${KONG_PORT}"
  export SUPABASE_DB_URL="$_db"
  export DATABASE_URL="$_db"           # engine RAG store (adcoherent_rag.config)
  export DATABASE_URL_API="$_db"
  export DATABASE_URL_WORKER="$_db"
  export DATABASE_URL_MIGRATIONS="$_db"
  export REDIS_URL="redis://:${REDIS_PASSWORD}@${REDIS_HOST}:${REDIS_PORT}/0"
  # The root .env carries CLAMAV_HOST=127.0.0.1 for HOST runs, so a
  # "${CLAMAV_HOST:-clamav}" fallback would never fire and every containerised
  # upload would fail closed with 503 scanner_unavailable. Override it the same
  # way the URLs above are overridden; CLAMAV_SERVICE_HOST is the escape hatch.
  export CLAMAV_HOST="${CLAMAV_SERVICE_HOST}"
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
