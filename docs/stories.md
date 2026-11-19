# Delivery backlog and acceptance criteria

Completion requires implementation plus tests. P0 is release-critical, P1 is product completeness, P2 is enhancement. Work packages are independently owned; integration is centrally reviewed. The status table below records the alpha's actual reduced scope; priorities are not silently relaxed by publication.

| ID | Priority | User story | Acceptance criteria | Package |
|---|---|---|---|---|
| S01 | P0 | As owner I securely initialize and sign in | One-time secret-gated setup; hashed password; expiring secure session; CSRF; unauthorized requests rejected | API |
| S02 | P0 | As owner I import a Finanzguru export | Exact headers/date/Decimal/German booleans; bounded safe XLSX; unknown fields retained; preview and counts | API |
| S03 | P0 | As owner I reimport without duplicates | File hash and stable booking/account keys; changed rows revisioned; missing rows flagged, not removed | API |
| S04 | P0 | As analyst I distinguish transfers and splits | One-sided transfer preserved; paired transfer not spending; balanced split counted once; uncertain reconciliation warned | API |
| S05 | P0 | As analyst I view correct currency-aware finances | No floats; no cross-currency totals; future rows excluded; incomplete balances/periods labeled | API |
| S06 | P0 | As owner I reserve money for irregular expenses | Account-backed/virtual buckets; no overlapping allocation; obligations and required contributions; 720/year=60/month | API |
| S07 | P1 | As owner I explore and correct transactions | Pagination/filter/detail; reversible category overrides without changing source | API/UI |
| S08 | P1 | As owner I manage accounts | Stable identity, rename/type/inclusion, balance history/ownership uncertainty | API/UI |
| S09 | P1 | As analyst I inspect recurring costs | Source/inferred confidence; annual cost; price change; evidence | API/UI |
| S10 | P0 | As owner I use a responsive localized dashboard | DE default/EN; accessible navigation; money strings; charts, honest empty/error states; themes | UI |
| S11 | P0 | As owner I manage imports in the browser | Upload/drop, preview, history/status/reconciliation/error, retry | UI |
| S12 | P0 | As analyst I ask an optional bounded AI agent | LangGraph typed read-only tools, consent, evidence, no raw banking identifiers, disabled default | AI/jobs |
| S13 | P0 | As owner I cap AI costs | Atomic reservation/settlement; global/channel/run budgets; pricing/allowlist; runtime/token/step/tool/concurrency limits | AI/jobs |
| S14 | P1 | As owner I receive proactive reports | Explicit opt-in; changed-import/weekly/monthly triggers; historical structured findings and acknowledge/dismiss | AI/jobs |
| S15 | P0 | As owner I receive safe ntfy reminders | Generic text, stale-import suppression, retries/history, local timezone/quiet hours, test button | AI/jobs |
| S16 | P1 | As operator I use a watched folder | Stable-file checks; persistent job, safe retries/claims; never delete source | AI/jobs |
| S17 | P0 | As operator I deploy and recover FinSight | Compose/migrations/health/non-root; backup and verified restore procedure | Integration |
| S18 | P0 | As contributor I can test safely | Synthetic fixtures only; unit/integration/E2E; dependency and secret CI; real export ignored | All |
| S19 | P0 | As maintainer I publish a privacy-reviewed OSS project | Apache-2.0, docs, templates, full history scan, authenticated public `finsight` repository | Integration |
| S20 | P1 | As owner I connect ChatGPT or another MCP client | Disabled default; remote Streamable HTTP; OAuth PKCE with explicit consent; expiring/revocable credentials; isolation and rate limits | MCP auth |
| S21 | P1 | As analyst I query finance through MCP | Typed bounded read-only overview/account/transaction/category/recurrence/bucket tools; currencies, filters, uncertainty and evidence preserved; no raw banking references | MCP tools |
| S22 | P1 | As analyst I reuse financial analysis workflows | Native MCP prompts for monthly review, spending comparison, subscription audit, bucket funding and safe-to-spend; resources document definitions and tool chains; no unsupported certainty | MCP tools/UI |

## Delivery status — 2026-11-14

| Stories | Actual status |
|---|---|
| S01–S04 | Core auth/import/reimport/transfer/split paths implemented and regression-tested; unsupported nested/cyclic graphs rejected. |
| S05–S06 | Core per-currency arithmetic and funding implemented; incomplete asset coverage, ambiguous same-day observations, historical allocation/settings versioning and some lifecycle UI remain. |
| S07–S10 | Explorer, reversible corrections, account editing, recurrence evidence and responsive DE/EN dashboard implemented; complete revision-diff UI, richer recurrence/health analysis and warning translations remain. |
| S11 | Partial: preview/upload/history work; persistent HTTP uploads/progress/retry need [#18](https://github.com/philiplorenz-code/finsight/issues/18). |
| S12–S14 | Partial: bounded fixed-topic LangGraph graph, budget gates and opt-in scheduled jobs are tested; adaptive free-text analysis and complete proactive finding coverage need [#19](https://github.com/philiplorenz-code/finsight/issues/19). |
| S15–S16 | Generic ntfy/outbox/reminder policy and stable-file durable jobs implemented; live ntfy delivery and exhaustive process-crash tests not performed. |
| S17–S19 | Compose, actual synthetic restore/browser rehearsal, CI and privacy-reviewed public repository delivered; not an independent production-security audit. |
| S20–S22 | MCP protocol/OAuth/scopes/management, 12 tools, 3 resources and 5 prompts implemented and tested locally through deployed proxy; live ChatGPT/public HTTPS verification pending operator setup. |

See [release status](release-status.md) for evidence, limitations and linked follow-up issues.

## Regression coverage

Header mapping; identical/overlapping changed imports; paired and one-sided transfers; deposits/withdrawals; annual insurance; normalized obligations; no double counting; split reconciliation; null contracts; recurrence; future dates; incomplete months; negative balances; multiple accounts/currencies; renaming; 13k-row import; monthly budget exhaustion; concurrent reservations; loop limits/provider failure/disabled AI; ntfy failure and suppression; malformed/zip-bomb/formula uploads; unauthorized/CSRF; error redaction; backup/restore.

## Orchestration

1. API owner implements schema, auth, import, deterministic finance and API tests under `apps/api`.
2. UI owner implements `apps/web` against documented routes, with synthetic-only presentation.
3. AI/jobs owner implements isolated integration modules and tests; coordinates model contracts with API owner.
4. Main integrator owns infrastructure, documentation, cross-package review, executable tests, privacy review and publication. No subagent may publish or inspect private values.

Deferred features and unmet acceptance criteria must be recorded in `docs/release-status.md`, never silently marked complete.
