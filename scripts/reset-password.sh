#!/usr/bin/env bash
# Set a new FinSight login password locally. Run from the repository root; you type the password yourself.
set -euo pipefail
docker compose exec api python -m app.admin reset-password "$@"
