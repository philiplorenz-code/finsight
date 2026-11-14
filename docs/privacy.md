# Privacy and security model

FinSight has no telemetry or automatic bank synchronization. Uploaded spreadsheets, account references, transaction details, model responses and database backups are sensitive. Run it only on infrastructure you control. Encryption at rest is an operator responsibility (encrypted disks and encrypted backups).

## Local data

The repository ignores spreadsheets, CSV exports, SQLite databases, data directories, backups, environment files and keys. Synthetic fixtures are generated in tests. Do not attach exports to GitHub issues or include real financial information in screenshots. Original uploaded values and historical revisions remain in the private database, even when an override changes the display.

## External processing

AI is disabled by default and requires provider configuration and explicit external-data consent. Tool outputs should be aggregated/minimized; no IBAN, raw reference or source metadata belongs in model messages. Aggregate spending remains personal information. Check the provider's residency, logging and retention policy before enabling it. Model-generated advice is not regulated financial advice.

Langfuse and other tracing must not be silently enabled. Provider SDK/debug logs can expose prompts; do not enable request-body logging in production. Reverse proxies should not log request bodies or credentials. Do not include financial details in ntfy URLs, topic names or generic notification bodies. Public ntfy topics are discoverable; use a private authenticated server for sensitive use.

## Operational controls

- Expose only HTTPS behind a trusted reverse proxy; set secure cookies.
- Keep the bootstrap token secret and rotate environment secrets after suspected exposure.
- Use strong unique passwords and restrict network access; initial release is not intended as a public multi-tenant service.
- Keep Docker, dependencies and database patched. CI scans are preventive signals, not proof of safety.
- Backups are as sensitive as the running database. Encrypt, restrict permissions, set a retention policy and test restoration.
- No private financial data may enter commit history. Inspect staged content and every commit before public pushes.

## Retention

There is no safe assumption that deletion of an import also deletes all derived historical evidence. Follow the release status for implemented purge support. For full installation erasure, export any needed records, stop services and securely remove private volumes and backups using your infrastructure's documented procedure. FinSight never deletes watched source spreadsheets automatically.
