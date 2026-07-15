#!/bin/sh
# One image, three processes (D2). $1 selects the entrypoint.
set -e
cd /repo/backend

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
