#!/usr/bin/env bash
# Deliberately requires an explicit destructive-operation confirmation.
set -euo pipefail
if [[ "$#" != 2 || "$2" != "--confirm-replace-database" || ! -f "$1" ]]; then
  echo "Usage: bash scripts/restore.sh PRIVATE.dump --confirm-replace-database" >&2
  echo "Stop api and worker first. This replaces data in the configured database." >&2
  exit 2
fi
docker compose exec -T db pg_restore --list < "$1" > /dev/null
docker compose exec -T db pg_restore --username=finsight --dbname=finsight --clean --if-exists --no-owner --single-transaction --exit-on-error < "$1"
echo "Restore complete. Start services, verify owner login and reconciliation."
