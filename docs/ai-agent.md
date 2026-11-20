# AI, worker and notification integration

## Delivered modules

Owned files: `apps/api/app/ai.py`, `apps/api/app/jobs.py`,
`apps/api/app/notifications.py`, `apps/api/tests/test_ai_jobs.py`, and this file.
No real workbook was accessed, no provider/ntfy request was sent, and nothing was
committed or published by this work package.

The modules follow `docs/api-contract.md`: synchronous SQLAlchemy sessions,
`app.db.Base`, string owner IDs, `app.auth.current_user`, and the shared
`app.models.Finding`. They do not introduce an extra framework or private model
registry. Import **all three modules before metadata creation or migration**.
New tables are `ai_policies`, `ai_runs`, `worker_jobs`, `worker_job_attempts`,
`notification_settings`, and `notification_history`. Include these in Alembic.
The core `findings` table stores AI findings with `kind="ai"`.

Follow-up for review findings 7–9: provider/environment wiring, explicit EUR
accounting, proven zero-call release and owner-based scheduling are implemented.
Schema integration adds nullable `ai_policies.budget_currency` and
`ai_runs.currency`, plus `notification_settings.reminder_minute` (default 0).
**Upgrade migrations must leave legacy currency markers NULL or explicitly USD,
never backfill them as EUR.** Old policies/runs require audited reconciliation
before another reservation; no automatic FX conversion or ledger deletion occurs.
Fresh ORM-created policies/runs explicitly use EUR. Include these columns in the
backend migration work; this package does not own migration files.
UI integration: label new AI budget/price/charge controls **EUR**, using
`budget_currency`/usage `currency`; never reuse the owner's financial-data
currency for AI costs. Historical rows must honor their individual run currency
or show an explicit legacy/unknown warning. UI files remain owned by the central
integrator and were not modified here.

## API registration

The current `app.main` already discovers these module-level routers and applies
global CSRF. No additional mounting is needed there. Its generated OpenAPI was
checked for AI/notification paths. For a different app factory,
the equivalent registration is:

```python
from fastapi import Depends
from app import ai, jobs, notifications  # registers shared metadata
from app.auth import require_csrf

app.include_router(ai.router, prefix="/api", dependencies=[Depends(require_csrf)])
app.include_router(notifications.router, prefix="/api", dependencies=[Depends(require_csrf)])
```

Do not duplicate a CSRF dependency if the parent API router already applies it.
Every endpoint authenticates through `current_user` and scopes queries by its ID.
The default AI router deliberately does **not** register `/findings`; the core
backend already owns the canonical findings list and lifecycle endpoints. It
stores compatible `body`, `status` and structured `evidence` fields there.
Factories `ai.create_router` and `notifications.create_router` support explicit
injected session/auth dependencies for tests or alternative integrations.

Additional endpoints, all relative to `/api`:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/ai/chat` | Bounded aggregate report, not unrestricted free-form chat |
| POST/PATCH | `/ai/consent` | Explicitly provision/refresh environment policy and record owner consent |
| GET/PATCH | `/ai/settings` | Owner consent, allowlisted model and Decimal EUR budgets |
| GET | `/ai/usage` | Latest 100 structured run liabilities, charges and token counts |
| GET | `/ai/runs/{id}/evidence` | Owner-scoped immutable query/aggregate snapshots |
| GET/PATCH | `/notifications/settings` | Separate notification opt-in and scheduling |
| POST | `/notifications/consent` | Provision configured ntfy endpoint and record event opt-in |
| POST | `/notifications/test` | Persist/queue a generic test; returns 202, not delivery confirmation |
| GET | `/notifications` | Latest 100 sent/failed/suppressed/uncertain records |

`/ai/chat` body: `{"topic":"cashflow","start":"2026-10-01","end":"2026-10-31","currency":"EUR"}`.
Topics are `cashflow`, `categories`, `coverage`. Response contains `run_id`,
plain-text `answer`, and evidence. Dates are bounded to 367 inclusive calendar
days. No arbitrary SQL, prompt, URL, tool name or provider configuration is
accepted. Render model output as text, never trusted HTML.
`agent_mode="fixed_topic"` is exposed in AI settings. This is a limited fixed-topic
LangGraph aggregate explainer, **not an adaptive financial analyst or arbitrary
chat agent**. Free-text questions, model-selected iterative query planning,
merchant/category-label tools and broader financial reasoning are deferred. No
free-text field is accepted merely to simulate a conversational interface.

## Explicit configuration, disabled by default

No policy/settings row means disabled. New rows also default to disabled, with
no consent and zero budgets. No provider import, watcher scan or external call
is required to serve normal API requests.

The adapters consume the exact names from `.env.example`. Compose passes `.env`
through `env_file` to API and worker. For direct Python startup, export the
variables into the process environment; these modules do not open `.env` files.
Environment configuration alone never records owner consent or creates a policy.

1. Keep `AI_ENABLED=false`, `AI_EXTERNAL_CONSENT=false`,
   `AI_PROACTIVE_ENABLED=false` and `NTFY_ENABLED=false` until configured.
2. Set `AI_PROVIDER_BASE_URL` (e.g. an operator-chosen compatible `/v1` URL),
   `AI_API_KEY`, `AI_MODEL`, and comma-separated `AI_MODEL_ALLOWLIST`. Matching is
   exact/case-sensitive. OpenAI-compatible models normally use LiteLLM's
   `openai/<model>` identifier. API key and base URL are explicitly forwarded to
   LiteLLM; there is no fallback to unrelated provider credential names. A
   compatible local server without auth still needs an explicit nonempty dummy
   key, rather than accidentally falling back to another provider credential.
3. Supply `AI_INPUT_EUR_PER_MILLION` and `AI_OUTPUT_EUR_PER_MILLION`, reviewed as
   conservative **EUR** rates for `AI_MODEL` only. Other allowlist entries do
   not inherit this pair of prices and are not provisioned as priced models.
4. After accepting external transmission, set both `AI_ENABLED=true` and
   `AI_EXTERNAL_CONSENT=true` in API/worker environments and restart them.
5. Log in normally. POST `/api/ai/consent` with cookie and `X-CSRF-Token`:

   ```json
   {"enabled":true,"external_consent":true,"proactive_consent":false}
   ```

   This endpoint creates/refreshes the authenticated owner's policy from the
   environment, atomically, without any provider request. It copies reviewed
   prices, budgets and runtime bounds; no secret is returned or persisted.
   To opt into scheduled reports separately, the operator must also set
   `AI_PROACTIVE_ENABLED=true` and the owner must explicitly send
   `proactive_consent=true`. To revoke, POST all three booleans false; revocation
   works even after the operator has removed credentials or disabled AI.
6. GET `/api/ai/settings` and `/api/ai/usage`; all new budget amounts are EUR.
   `/ai/settings` PATCH can lower nominal policy budgets. Effective runtime and
   money caps are the **minimum** of persisted policy and operator environment.
   The generic core `/settings` integration form may also configure persisted
   rows; built-in real calls still enforce operator switches, exact model/rates,
   EUR markers and all environment ceilings. Never put secrets in that form.

Repeating `/ai/consent` refreshes nominal configuration from the environment,
including budgets, but never resets usage/history. Changes to model prices
require this refresh; mismatched persisted/operator rates fail closed. Merely
setting an environment consent flag does not substitute for authenticated owner
consent. Setting an operator switch false prevents new built-in external calls.

An allowlisted model's price entry is:

```json
{"input":"1.00000000","output":"2.00000000","currency":"EUR","verified":true}
```

These numbers are **synthetic examples**, not current provider prices. Rates
are conservative EUR per million input/output tokens, verified by the operator
against their provider agreement. USD prices are **rejected**, never silently
treated as EUR. For USD-billed providers the operator must explicitly calculate
conservative EUR-equivalent rates including FX/fees/headroom, or leave AI off;
FinSight does not fetch exchange rates or infer a conversion. Decimal strings
only, at most eight decimal places. Restrict
the allowlist to plain-text models billed using these two token classes, with
usage counters covering all billable tokens. Models with unaccounted request,
audio, search or other fees are unsupported. Provider credentials remain in
`AI_API_KEY` and `AI_PROVIDER_BASE_URL`; they are not request fields,
queue payloads, histories or API responses.

Optional `/ai/settings` PATCH for an already provisioned policy requires:

```json
{"enabled":true,"external_consent":true,"proactive_consent":false,
 "model":"operator-configured/model","total_limit":"5","monthly_limit":"1",
 "run_limit":"0.02","channel_limits":{"chat":"1"}}
```

All amounts above are EUR. Pricing cannot be changed by this request. The env
pair prices only the configured `AI_MODEL`; selecting another model requires a
reviewed operator reconfiguration and explicit policy refresh.

Environment caps applied on every built-in real run:

| Variable | Default / meaning |
| --- | --- |
| `AI_MONTHLY_BUDGET_EUR` | 5.00, all channels combined per UTC month |
| `AI_CHAT_BUDGET_EUR` | 3.00, chat per UTC month |
| `AI_SCHEDULED_BUDGET_EUR` | 2.00, **shared** across weekly/monthly/changed-import |
| `AI_MAX_RUN_COST_EUR` | 0.25, worst-case reservation per run |
| `AI_TOTAL_BUDGET_EUR` | Optional extension: lifetime cap; defaults conservatively to monthly budget |
| `AI_MAX_INPUT_TOKENS` | 8000; accepted 128–32000 |
| `AI_MAX_OUTPUT_TOKENS` | 2000; accepted 1–4096 |
| `AI_MAX_AGENT_STEPS` | 8; accepted 3–8 |
| `AI_MAX_TOOL_CALLS` | 20; accepted 1–20 (current graph actually uses one) |
| `AI_MAX_RUNTIME_SECONDS` | 90; accepted 1–120 |
| `AI_MAX_CONCURRENT_RUNS` | 1; accepted 1–8 unresolved runs |
| `AI_RETRY_LIMIT` | Must be exactly 0; nonzero fails configuration preflight |

Missing credentials/rates, invalid bounds, disabled switches, unallowlisted
models and nonzero retries fail before any reservation or transmission. A
lifetime cap is intentionally not reset by a new month or consent refresh.

Notifications are configured with an operator-controlled HTTP(S) ntfy server
and a strict topic identifier. HTTP permits explicitly chosen self-hosted LAN
servers; prefer HTTPS. URL credentials, query strings, fragments and redirects
are prohibited. `NTFY_ACCESS_TOKEN` supplies the bearer secret; the obsolete
`FINSIGHT_NTFY_TOKEN` name is not used. Do not place auth in the stored URL. A
custom worker factory can provide per-owner secret lookup.

Set `NTFY_SERVER_URL`, `NTFY_TOPIC`, optionally `NTFY_ACCESS_TOKEN`, then
`NTFY_ENABLED=true` and restart the API/worker. Authenticated POST
`/api/notifications/consent` with
`{"enabled":true,"events":["weekly","monthly","report_ready"]}` provisions
the endpoint from the environment and records separate event consent. It sends
nothing; use `/notifications/test` to enqueue a generic test afterwards.
Provisioning consumes `NTFY_REMINDER_DAYS` (default 14; stale horizon),
`NTFY_REMINDER_TIME` (09:00, minute precision), `NTFY_QUIET_START` (22:00) and
`NTFY_QUIET_END` (08:00). Explicit fields in the request override schedule
defaults, never the endpoint/auth. Existing stored settings are not silently
overwritten at startup. The default handler also enforces `NTFY_ENABLED` as an
operator kill switch before delivery.

Notification consent fields: `enabled`, `events`, `timezone`, `quiet_start`,
`quiet_end`, `stale_after_hours`, `reminder_hour`, `reminder_minute`, `weekly_day`. Quiet times are
minutes after local midnight; weekday 0 is Monday. The server/topic are not
editable through this HTTP endpoint. Default zone is Europe/Berlin, quiet hours
22:00–08:00. Bare ORM defaults use seven-day staleness; environment provisioning
uses the configured `NTFY_REMINDER_DAYS` (14 by default). Equal quiet endpoints disable quiet hours.
The test button bypasses stale-import checks, **not** consent or quiet hours.

An operator-configured `APP_URL` adds a generic ntfy view action and click target
for `/imports` or `/insights`. Only a public origin is accepted: private paths,
credentials, query strings, fragments and header delimiters are rejected. An
invalid/missing origin omits the link rather than exposing sensitive URL data.

## Agent and budget semantics

LangGraph executes a typed fixed plan, a bounded read-only tool iteration, and
one explanation node. The model cannot select or add tools. The deterministic
adapter calls the backend `finance.overview` with the authenticated owner and
date range. Backend transfer/split/future-date rules therefore also apply to AI.
Only fixed metric keys, decimal numeric strings and a selected currency leave
the process. No account IDs, descriptions, merchants, categories, raw source,
filenames or bank identifiers are supplied to the provider. The category tool
currently discloses combined spending, **not category labels or a category
breakdown**. Coverage is explicitly not established (zero), not invented.

Evidence retains the exact typed local query, query timestamp and aggregate
snapshot. It is resolvable through the run evidence endpoint and remains useful
after later imports/overrides change a re-run's results. Model explanations are
untrusted interpretations, not verified anomaly detection or financial advice.
LiteLLM is lazy-loaded only after consent/reservation; telemetry and debug info
are disabled and its local cost map is selected. There are no application-level
provider retries, model fallbacks, streaming calls or model-driven SQL.

Reservation locks the pre-provisioned policy row with PostgreSQL `FOR UPDATE`,
then checks total lifetime liability, UTC-month liability, monthly channel cap,
per-run cap and unresolved concurrency. The full maximum input+output price is
rounded **up** to eight decimal places and committed **before** network I/O.
All channels share the owner's total/monthly budget. This is the single-owner
release's global budget, not a deployment-wide shared cap across future users.
PostgreSQL READ COMMITTED isolation is required and checked on reservation;
alternative isolation settings are rejected rather than risking stale snapshots.
The built-in real provider and default worker refuse SQLite. SQLite tests use
injected synthetic providers and queue logic only.
The environment scheduled cap is additionally shared across all proactive
channels under the same row lock, not copied into three independent allowances.
Usage records carry their own immutable budget currency. Legacy USD/unknown
records remain explicitly labeled and block new EUR reservations until audited;
they must never be displayed as EUR charges by the UI.

Verified token usage settles against the run's immutable price snapshot. Missing,
invalid or excessive usage, transmitted provider failure, cancellation after
transmission, timeout after transmission and ambiguous crashes retain the full
reservation. Uncertain runs retain their concurrency slot too.
Unresolved liabilities carry into subsequent months; late settlements count in
both reservation and settlement months conservatively. Do not delete rows,
expire reservations or free a slot based on elapsed time. Operator reconciliation
against real billing is required; a reconciliation UI/API is not implemented.
Changing prices or disabling the integration does not erase prior liability.
The graph tracks the conservative transmission boundary immediately before
LiteLLM invocation. Proven zero-call input/tool/aggregate validation failures,
local pre-call failures and cancellation before invocation persist a distinct
`released` state with zero charge; original reservation remains for audit.
These records consume neither budget liability nor concurrency. A crash with no
durable proof of zero transmission is still retained, never guessed free.

Input serialization has a conservative byte/token envelope and actual usage is
checked before releasing any reservation. Operator model/tokenizer compatibility
still requires verification. Read queries use a managed asyncio executor and
PostgreSQL per-statement timeout; graph cancellation cannot forward a late query
result to the provider. It cannot forcibly terminate a running Python thread.

## Worker, watcher and schedules

Run migrations first, then from `apps/api`:

```sh
python -m app.jobs
```

Default factory is `app.jobs:default_worker_factory`. Override with
`FINSIGHT_WORKER_FACTORY=trusted.module:factory` or `--factory`. A factory returns
`(session_factory, handlers, poll_hook)`. No code path/handler is imported from
an untrusted job payload. Multiple worker processes share PostgreSQL; each
process runs one handler at a time. Polling is every 30 seconds in the default
factory. Core users/imports are owner-scoped; latest completed import updates
notification freshness.

Claims use `FOR UPDATE SKIP LOCKED`, persisted attempts, lease expiry and random
fencing tokens. Completion/heartbeat/deferral must match the token and a live
lease. Failed replay-safe work backs off exponentially (bounded attempts); old
workers cannot complete newer claims. Expired non-replayable work becomes
uncertain. Handlers must implement their own replay safety and transactionally
check the token for database mutations; a queue cannot make external services
exactly once. Handler timeout is shorter than the lease. Job payloads/history
must not contain secrets, exception messages or arbitrary private documents.
The shipped CLI sets its handler timeout above `AI_MAX_RUNTIME_SECONDS`, with a
further lease margin; a configured 90-second graph is not cut off by the former
60-second worker default.

Watching is **off** unless both `FINSIGHT_WATCH_IMPORTS=true` and
`FINSIGHT_WATCH_OWNER_ID=<existing owner UUID>` are configured. Only the fixed
`/data/imports` mount is scanned; do not mount a broad home/source directory.
Two unchanged observations and minimum age precede bounded SHA-256 hashing.
Symlinks are rejected with `O_NOFOLLOW`; files larger than 32 MiB are ignored.
The core importer revalidates the digest and XLSX safety limits. Imports serialize
per owner with a live claim-row lock, use a full snapshot for "Alle Buchungen" files (`FINSIGHT_WATCH_FULL_SNAPSHOT`, default `auto`), and preserve all
source files. Ingestion is synchronous; parser resource limits, not asyncio
cancellation, bound CPU parsing. The core importer commits internally; a crash
between import commit and job completion is handled through digest idempotency.

Fresh completed imports can schedule changed-import reports, Monday reports for
the prior week, and first-of-month reports for the prior month. AI requires
separate proactive consent **and positive caps for each channel**. UTC budget
months are distinct from the local-time schedule. These jobs are not replayed
automatically because duplicate provider charges cannot be made idempotent.
Report currency/timezone come from the owner's core `Setting.data` preferences,
independent of notification configuration. A USD owner without ntfy settings
gets USD financial aggregates (while AI costs/budgets remain EUR). Invalid
preferences skip scheduling, rather than silently changing the denomination or
calendar. Changed-import reports/notifications require positive integer
`summary.added` or `summary.changed`; unchanged/unknown summaries do not trigger
them. Independent weekly/monthly schedules remain enabled when opted in.
Weekly/monthly/report-ready/import-changed notifications have separate event
opt-ins and dedupe keys. `queue_notification(..., "anomaly", stable_event_key)`
is available for a future deterministic detector; no detector is fabricated.
Missed weekly/monthly schedule days are not automatically backfilled.

ntfy sends one fixed generic message, never balances or finding text. Quiet
windows are evaluated in the configured zone with DST-safe UTC traversal.
Freshness and consent are checked again immediately before delivery. Quiet-hour
deferrals do not consume retries. Connection failure/429 can retry; ambiguous
read timeout, 5xx, process crash after entering `sending`, or unknown delivery
becomes uncertain and is not automatically resent. A crash after a successful
send but before its DB commit cannot be guaranteed exactly once. Histories
make that uncertainty visible. Suppressed notifications are retained.

## Verification and limits

```sh
cd apps/api
.venv/bin/python -m pytest tests/test_ai_jobs.py -q
.venv/bin/python -m app.jobs --help
```

Synthetic unit/graph/SQLite/HTTP-mock tests: **78 passed, 1 skipped**. A PostgreSQL test is included
but skipped unless `FINSIGHT_TEST_POSTGRES_URL` points to an **isolated test DB**.
It creates/drops a random synthetic schema to test simultaneous reservations and
SKIP LOCKED claims. SQLite does not verify PostgreSQL row-lock behavior.
The central session reports its separate real PostgreSQL reservation/job tests
passed; those tests were not replaced or edited here. Follow-up tests cover the
documented credential names with mocked transports, authenticated environment
provisioning, exact EUR prices/limits, shared scheduled caps, zero-call releases,
post-call cancellation retention, USD-only owner activity/timezone with no ntfy
settings, and unchanged-import suppression. No real request was made.

Not verified here: live PostgreSQL concurrent workers, Alembic upgrade/restore,
Compose deployment, real provider tokenizer/billing/timeout behavior, actual
ntfy transport/auth, long-running crash recovery and the web settings UI. No
real workbook was used. Before release the integrator must run those tests and
record these limitations in `docs/release-status.md`. No production-ready claim
is made by this work package.
