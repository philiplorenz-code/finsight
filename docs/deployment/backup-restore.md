# Backup and restore

Backups contain private financial data, password hashes and integration history. Restrict access, encrypt before off-site transfer and define your retention policy. Never commit backups. Application backups do not replace secure storage of configuration secrets or original source exports.

## Backup

From the repository root with Compose running:

```sh
bash scripts/backup.sh
```

The script creates a mode-restricted custom-format PostgreSQL dump atomically and validates its table of contents. `pg_dump` provides a transactionally consistent database snapshot. Keep an encrypted copy of `.env` separately. Preserve original private watched/upload files separately if needed; database backups do not include import-directory volume contents.

## Restore

Test first in an isolated Compose project with synthetic data. A production restore replaces data:

```sh
docker compose stop api worker
bash scripts/restore.sh backups/PRIVATE.dump --confirm-replace-database
docker compose run --rm migrate
docker compose up -d api worker web
```

Use a compatible PostgreSQL major version and application version. Verify login, account counts, import history, financial totals per currency and job state. Disable external integrations during a recovery rehearsal to avoid duplicate notices/provider calls. Existing sessions and queued jobs are restored with the database; invalidate them if the backup is suspected compromised.

## Recovery rehearsal acceptance

1. Create synthetic accounts/transactions and note deterministic totals.
2. Back up; restore into a separate empty project/volume.
3. Compare synthetic row counts, balances, allocations and import checksums.
4. Confirm migration revision and health endpoints.
5. Keep a dated recovery record without private financial figures.

A backup is not proven recoverable until this rehearsal passes. See release status for the last verified environment.
