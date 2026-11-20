#!/usr/bin/env bash
# Timestamped backup with retention, meant for cron/launchd. Run from the repository root:
#   scripts/scheduled-backup.sh [keep=14] [directory=backups]
# Backups are plaintext dumps: keep the directory private and encrypt before copying off-site.
set -euo pipefail
cd "$(dirname "$0")/.."
keep="${1:-14}"
dir="${2:-backups}"
# Refuse to write into a nearly full disk; a failed dump would only add to the problem.
free_kb=$(df -Pk "$dir" 2>/dev/null | awk 'NR==2 {print $4}' || true)
if [[ -n "${free_kb:-}" && "$free_kb" -lt 1048576 ]]; then
  echo "Less than 1 GiB free; skipping backup." >&2
  exit 1
fi
bash scripts/backup.sh "$dir/finsight-$(date -u +%Y%m%dT%H%M%SZ).dump"
# Keep only the newest $keep dumps.
ls -1t "$dir"/finsight-*.dump 2>/dev/null | tail -n +"$((keep + 1))" | while read -r old; do rm -f -- "$old"; done
