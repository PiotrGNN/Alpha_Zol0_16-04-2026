#!/usr/bin/env bash
set -euo pipefail

: "${PAID_BETA_DATABASE_URL:?PAID_BETA_DATABASE_URL is required}"
: "${PAID_BETA_RESTORE_DATABASE_URL:?PAID_BETA_RESTORE_DATABASE_URL is required}"
: "${PAID_BETA_STAGING_REHEARSAL:?set PAID_BETA_STAGING_REHEARSAL=1}"

if [[ "${PAID_BETA_STAGING_REHEARSAL}" != "1" ]]; then
  echo "BLOCKED: PAID_BETA_STAGING_REHEARSAL must equal 1" >&2
  exit 2
fi

if [[ "${PAID_BETA_DATABASE_URL}" == "${PAID_BETA_RESTORE_DATABASE_URL}" ]]; then
  echo "BLOCKED: source and restore databases must be different" >&2
  exit 2
fi

if [[ "${PAID_BETA_DATABASE_URL}" != postgresql://* ]]; then
  echo "BLOCKED: source must use postgresql://" >&2
  exit 2
fi

if [[ "${PAID_BETA_RESTORE_DATABASE_URL}" != postgresql://* ]]; then
  echo "BLOCKED: restore target must use postgresql://" >&2
  exit 2
fi

existing_tables="$(psql "$PAID_BETA_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")"
if [[ "$existing_tables" != "0" ]]; then
  echo "BLOCKED: restore target must be a new empty disposable database" >&2
  exit 2
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
backup="$workdir/paid-beta-staging.dump"

source_revision="$(psql "$PAID_BETA_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc 'SELECT version_num FROM alembic_version')"
if [[ "$source_revision" != "0003_revenue_readiness_gate" ]]; then
  echo "BLOCKED: source schema revision is not 0003_revenue_readiness_gate" >&2
  exit 2
fi

pg_dump --format=custom --no-owner --no-acl \
  --dbname="$PAID_BETA_DATABASE_URL" --file="$backup"
test -s "$backup"

pg_restore --no-owner --no-acl --exit-on-error \
  --dbname="$PAID_BETA_RESTORE_DATABASE_URL" "$backup"

restore_revision="$(psql "$PAID_BETA_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc 'SELECT version_num FROM alembic_version')"
if [[ "$restore_revision" != "$source_revision" ]]; then
  echo "FAILED: restored schema revision differs from source" >&2
  exit 1
fi

for table in paid_beta_users paid_beta_artifacts paid_beta_artifact_grants paid_beta_checkout_sessions paid_beta_webhook_events paid_beta_economics_periods; do
  source_count="$(psql "$PAID_BETA_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM ${table}")"
  restore_count="$(psql "$PAID_BETA_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT count(*) FROM ${table}")"
  if [[ "$source_count" != "$restore_count" ]]; then
    echo "FAILED: row-count mismatch for ${table}" >&2
    exit 1
  fi
done

echo "paid-beta staging backup/restore rehearsal: PASS"
