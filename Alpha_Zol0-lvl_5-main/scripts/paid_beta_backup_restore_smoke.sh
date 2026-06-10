#!/usr/bin/env bash
set -euo pipefail

echo "BLOCKED: use managed PostgreSQL snapshot or PITR for operator backups; use paid_beta_staging_backup_restore_rehearsal.sh only with a new empty disposable restore database" >&2
exit 2
