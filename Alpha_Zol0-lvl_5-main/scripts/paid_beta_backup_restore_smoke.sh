#!/usr/bin/env bash
set -euo pipefail

: "${PAID_BETA_DATABASE_URL:?PAID_BETA_DATABASE_URL is required}"
: "${PAID_BETA_RESTORE_DATABASE_URL:?PAID_BETA_RESTORE_DATABASE_URL is required}"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
backup="$workdir/paid-beta.dump"

pg_dump --format=custom --no-owner --no-acl --dbname="$PAID_BETA_DATABASE_URL" --file="$backup"
test -s "$backup"

psql "$PAID_BETA_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'
pg_restore --no-owner --no-acl --exit-on-error --dbname="$PAID_BETA_RESTORE_DATABASE_URL" "$backup"

psql "$PAID_BETA_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'paid_beta_users'
  ) THEN
    RAISE EXCEPTION 'paid_beta_users missing after restore';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'paid_beta_artifacts'
  ) THEN
    RAISE EXCEPTION 'paid_beta_artifacts missing after restore';
  END IF;
END $$;
SQL

echo "paid-beta backup/restore smoke: PASS"
