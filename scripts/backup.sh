#!/usr/bin/env bash
# Run from repository root. Plaintext backup: encrypt before off-site storage.
set -euo pipefail
umask 077
target="${1:-backups/finsight-$(date -u +%Y%m%dT%H%M%SZ).dump}"
if [[ -e "$target" || -e "$target.partial" ]]; then
  echo "Refusing to overwrite an existing backup." >&2
  exit 1
fi
mkdir -p "$(dirname "$target")"
trap 'rm -f -- "$target.partial"' EXIT
docker compose exec -T db pg_dump --username=finsight --dbname=finsight --format=custom > "$target.partial"
docker compose exec -T db pg_restore --list < "$target.partial" > /dev/null
mv -- "$target.partial" "$target"
echo "Backup created. Treat it as private and encrypt it before transfer."
