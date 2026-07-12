#!/usr/bin/env bash
# Apply SaaS migrations to the self-hosted Supabase Postgres, in order,
# skipping files already recorded in app.schema_migrations.
#
#   ./apply.sh            # apply pending migrations via the supabase-db container
#   PSQL="psql $DATABASE_URL" ./apply.sh   # or through any psql connection
set -euo pipefail

cd "$(dirname "$0")"
PSQL="${PSQL:-docker exec -i supabase-db psql -U postgres -d postgres}"

$PSQL -v ON_ERROR_STOP=1 -q <<'SQL'
create schema if not exists app;
create table if not exists app.schema_migrations (
  filename   text primary key,
  applied_at timestamptz not null default now()
);
SQL

for f in migrations/*.sql; do
  name="$(basename "$f")"
  applied="$($PSQL -Atq -c \
    "select 1 from app.schema_migrations where filename = '$name';")"
  if [ "$applied" = "1" ]; then
    echo "skip    $name (already applied)"
    continue
  fi
  echo "apply   $name"
  $PSQL -v ON_ERROR_STOP=1 -q < "$f"
  $PSQL -Atq -c \
    "insert into app.schema_migrations (filename) values ('$name');" > /dev/null
done

echo "done."
