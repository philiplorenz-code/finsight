# Configuration and operations

Configuration secrets belong in the private `.env` file, not Git. Never paste `docker compose config` output publicly: variable expansion can reveal passwords. Use `docker compose config --quiet` for validation.

## Core settings

| Variable | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | Required private database password; generate a long random hex string |
| `FINSIGHT_BOOTSTRAP_SECRET` | Required one-time owner setup authorization; different from DB password |
| `FINSIGHT_DATABASE_URL` | Backend DB URL; Compose supplies its internal PostgreSQL URL |
| `FINSIGHT_COOKIE_SECURE` | `false` for localhost HTTP only, `true` for HTTPS deployments |
| `FINSIGHT_SESSION_HOURS` | Server-side session lifetime, default 24 hours |
| `FINSIGHT_ALLOWED_ORIGINS` | JSON array of exact trusted origins for reverse-proxy login/setup |
| `FINSIGHT_MAX_UPLOAD_BYTES` | Maximum compressed upload size |
| `FINSIGHT_MAX_UNCOMPRESSED_BYTES` | Maximum expanded workbook size |
| `FINSIGHT_MAX_IMPORT_ROWS` | Maximum transaction rows |
| `BIND_ADDRESS` / `PORT` | Host web listener; default `127.0.0.1:8080` |
| `APP_URL` | Public origin for generic ntfy dashboard buttons; no credentials, private path, query or fragment |

## HTTPS deployment

Put the web service behind a TLS reverse proxy you administer. Preserve the original Host header and allow only the intended canonical origin. Set `FINSIGHT_COOKIE_SECURE=true`. Do not publish the database or API port, and do not trust arbitrary forwarded client IP headers. Login rate limits deliberately do not treat untrusted forwarded addresses as identity.

Do not mount the host Docker socket into FinSight containers. Restrict network access to your household/VPN where possible. Rootless application containers and dropped capabilities do not make arbitrary public exposure safe.

## AI and notification configuration

Both are opt-in. See [AI agent](../ai-agent.md) for the exact policy and provider configuration supported by this version. Budget limits are conservative application estimates, not a provider billing guarantee. Uncertain billed calls retain reservations until reconciled; blindly releasing reservations can defeat the cap.

ntfy notification bodies remain generic. `APP_URL` adds a generic dashboard button (`/imports` or `/insights`), never a transaction-specific link; unsafe URLs are omitted. Use an authenticated self-hosted server when possible. `ntfy.sh` topic names are not passwords. Never place tokens, financial details or account references in URLs. Quiet hours and reminder timing use the configured local timezone; UI and worker policies must agree.

## Watched directory

The optional worker watcher uses `/data/imports`. Set `FINSIGHT_WATCH_IMPORTS=true` and the explicit `FINSIGHT_WATCH_OWNER_ID` from `/api/auth/me`. Copy files atomically (write a different suffix then rename to `.xlsx`) or allow the stability delay to elapse. It never deletes input files. Keep private exports in the dedicated volume, not in source code. See AI/jobs documentation for enablement and explicit owner selection.

## Upgrades

1. Back up and test your recovery plan.
2. Read release notes and outstanding limitations.
3. Pull reviewed source changes; rebuild images.
4. Run migrations before starting the new API/worker (`docker compose up -d --build` coordinates this).
5. Check health, owner login, import history and currency-specific totals.

Do not restore an old application against a newer schema without a tested migration plan.

## Troubleshooting

- **Setup denied:** check the bootstrap environment value privately; setup is unavailable after an owner exists. Do not publish the value.
- **Login succeeds but session is absent:** secure cookies are not sent on plain HTTP. Use HTTPS or set the local-only insecure-cookie option.
- **403 on mutations:** refresh/login to obtain a current CSRF token; verify Host/origin forwarding. Never disable CSRF as a fix.
- **Upload rejected:** verify `.xlsx`, one worksheet, required columns, no formulas/external links/macros and configured resource limits. Error messages deliberately omit cell contents.
- **Totals differ from bank:** inspect interval, currency, account inclusion, missing opening balances, source transfers, split warnings and future dates. Imported observations are not complete net worth.
- **AI refused:** ensure explicit consent, configured model pricing/allowlist, provider credentials and available global/channel/run/concurrency budgets. Unknown usage intentionally fails closed.
- **No reminders:** check separate notification enablement, topic/server, quiet hours, reminder age, worker status and recent successful import suppression.
- **Worker unavailable:** inspect job history and redacted error codes; do not print provider response bodies or spreadsheet rows while debugging.
- **Database not ready:** check private volume permissions and `docker compose ps`; never delete the volume as a troubleshooting shortcut.

For public bug reports use only synthetic reproduction and redacted version/status information.
