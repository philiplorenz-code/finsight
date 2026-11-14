# FinSight source review — security and financial integration

## Integrator verification addendum — 2026-11-14

The original review below is retained as a dated inspection record, not a current release-blocker list. Subsequent verification resolved items **1 and 10**: the shipped proxy preserves `$http_host`, deployed browser/API tests accept same-origin login and reject hostile origins, and the importer atomically rejects nested, cyclic and self-referencing split graphs. `test_nested_splits.py` covers permutations and partial/repeated imports. The final pre-MCP combined suite passed **216 tests and 66 subtests**; real PostgreSQL overlap/import-revision tests passed. A populated dashboard also passed the mobile width guard at 390px after waiting for the chart resize, rather than masking overflow.

The actual [baseline GitHub CI run](https://github.com/philiplorenz-code/finsight/actions/runs/43637165777) passed API/PostgreSQL tests and dependency audit, frontend build/unit/browser tests, publication/secret scans, clean Compose startup, deployed same-origin auth/import/browser checks and synthetic backup/restore verification. Docker configuration is in `infrastructure/docker/api.Dockerfile`, not `apps/api/Dockerfile`. This evidence does not imply full target-story acceptance or an independent security audit. See [release status](release-status.md) for deferred requirements and the separately reviewed MCP increment.

---

Review / follow-up date: 2026-11-14. Only source/configuration/test files were read. No private `.env`, actual workbook, application database, provider, or deployment was accessed. No tests were executed by this reviewer. “Fixed in source” below means implementation and targeted test assertions were inspected, not that this reviewer observed a passing run. Original descriptions/line references are retained for traceability; follow-up references identify current source.

## Follow-up summary

| Original item | Resolution at follow-up |
|---|---|
| 1 — proxy origin / public port | **Pending UI owner's in-flight fix and deployed browser verification**; not reclassified as fixed based on work in progress. |
| 2 — stale split parent | **Fixed in source; targeted regressions present.** Separate nested-split defect remains below as item 10. |
| 3 — scheduled bucket contributions | **Fixed in source; targeted regressions present.** |
| 4 — stale allocation backing | **Fixed in source; targeted regressions present.** |
| 5 — HTTP import serialization | **Fixed in source; lock-order/cache-refresh tests present.** Real PostgreSQL import/allocation concurrency evidence still pending. |
| 6 — numeric XLSX float conversion | **Fixed in source; exact XML lexeme tests present**, including nonstandard worksheet relationship targets. UI display precision is separate in-flight work and is not signed off here. |
| 7 — integration environment wiring | **Fixed in source; mocked adapter/provisioning regressions present.** |
| 8 — zero-transmission AI liability | **Fixed in source; release/cancellation regressions present.** |
| 9 — proactive report currency/timezone | **Fixed in source; owner-preference regression present.** AI cost denomination is now explicitly EUR, independent of report-data denomination. |

**Remaining concrete accounting blocker:** item 10 (nested split order-dependent double counting). No new owner-authorization bypass or AI reservation bypass was established in this follow-up. Item 1 remains an outstanding integration gate, not a claimed completed fix.

**Execution evidence:** Main session reports an earlier root pytest result of 180 passed / 2 failed due to relative Alembic configuration. The absolute `CONFIG_PATH` fix in `apps/api/tests/test_migrations.py:11-18,32` and `%(here)s` paths in `apps/api/alembic.ini:2-3` are present. Its 192-case rerun is **pending / not observed by this reviewer**. Live Compose, browser and backup/restore runs are **not yet verified**. Do not turn source/test inspection or declared CI into a production-readiness claim.

## Original findings, with resolution evidence

### 1. P0 — Default reverse proxy breaks browser setup/login origin validation

**Follow-up: PENDING.** UI owner is currently addressing the public-port bug. No in-flight UI source was used here as final resolution evidence. Require the original same-origin/attacker-origin checks through the actual deployed proxy, including browser Origin headers.

- **Locations:** `apps/web/nginx.conf:19-22`; `apps/api/app/auth.py:49-54`; `docker-compose.yml:74-75`; `scripts/compose_smoke.py:32-43`.
- Nginx forwards `Host $host`, stripping the public port. A browser POST from `http://localhost:8080` has that exact Origin, but the API reconstructs `http://localhost` and rejects it. `allowed_origins` defaults empty; `APP_URL` in the example configuration is not consumed by Settings. TLS termination adds another scheme mismatch unless explicitly/trustworthily handled.
- The deployed smoke client supplies no Origin, so its successful authentication would not catch this defect.
- **Fix:** Define a trusted canonical public origin or preserve the validated public authority (including port), with explicit proxy trust/scheme configuration. Do not disable origin validation or trust arbitrary forwarded headers.
- **Regression:** Through the shipped proxy, test setup/login with the real `Origin: http://localhost:8080`; accept same-origin, reject attacker origin. Include custom port and documented HTTPS proxy topology. Browser E2E must use the deployed API, not mocked auth.

### 2. P1 — Removing a split relationship leaves the old parent excluded forever

**Follow-up: FIXED IN SOURCE.** `importer.py:114-123,346-353` rebuilds source-only split and transfer classifications for every retained transaction before deriving groups. `apps/api/tests/test_review_regressions.py:34-64` asserts removal of links restores the unchanged parent and clears inherited transfer flags across partial/repeated imports. These tests were inspected, not rerun here. See item 10 for a distinct nested-group defect.

- **Locations:** `apps/api/app/importer.py:265-270,296-315`; `apps/api/app/finance.py:48-49`.
- Reconciliation only visits currently referenced parents. After importing parent -100 and children -60/-40, the parent becomes `parent`. If a later revision removes both child-parent links, the children update, but the unchanged parent retains `split_role='parent'`; it is never reset because the group no longer exists. A valid independent parent movement is silently omitted.
- **Fix:** Recompute derived split roles for all affected old and new groups from source metadata; do not use stale derived roles as inputs. Keep source and derived classification separate.
- **Regression:** Import a balanced split, then revise both children to independent rows with no parent metadata. Assert the parent is restored and totals/categories reflect all three independent movements; repeat unchanged and overlapping partial imports to check stability.

### 3. P1 — Bucket funds are consumed before scheduled contributions, overstating funding needs

**Follow-up: FIXED IN SOURCE.** `finance.py:112-113,124-133` sorts by effective due date, subtracts each obligation's own scheduled contributions first, and never shares its excess. `test_review_regressions.py:67-91` covers fully scheduled funding, excess contributions, inherited dates and required-period arithmetic.

- **Location:** `apps/api/app/finance.py:64-71`.
- `covered = min(available, item.amount)` consumes funds before subtracting that obligation's scheduled contributions. Example: funded 500, first obligation 400 with scheduled contributions 400, second obligation 400 without scheduled contributions. Existing funds can cover the second obligation completely, but the function reports an additional 300 needed (with one remaining period).
- **Fix:** Apply obligation-specific scheduled funding to its debit first, then consume shared bucket funds against the remaining debit. Document contribution timing; order by effective due date (`item.due_date or bucket.due_date`), not just nullable obligation dates.
- **Regression:** The example above must require zero; additionally test contributions exceeding the debit, mixed due dates/periods, and explicit dates mixed with bucket-inherited due dates.

### 4. P1 — Allocations remain reported as funded after backing funds disappear or become ineligible

**Follow-up: FIXED IN SOURCE.** `finance.py:67-106,109-141,197-217` distinguishes nominal intent from currently backed funds, assigns each account's capacity once in stable bucket/allocation order, exposes shortfall/status/warnings, and shares backing with overview. Negative eligible balances remain negative liquidity. `test_review_regressions.py:94-140` covers reduced/negative balances, excluded/external/unknown/investment accounts, and two competing buckets. Assertions check bucket/overview consistency, not just warning presence.

- **Locations:** `apps/api/app/routes.py:93-99,295-313`; `apps/api/app/finance.py:58-60,129-143`; `apps/api/app/importer.py:293-294`.
- Allocation eligibility/capacity is checked only on allocation PUT. A later lower balance, exclusion, external ownership change, or switch to investment leaves allocations unchanged. `bucket_json` still reports the full amount as funded and reduces required contributions, even when no eligible backing funds remain. Overview may omit the allocation for excluded/external accounts while the bucket still claims it is funded. There is no explicit underfunded/ineligible warning.
- **Fix:** Reconcile or visibly invalidate funding on balance/account changes. Separate nominal allocation intent from currently backed funding, and use one consistent eligibility rule for bucket and overview calculations. Preserve negative liquidity rather than clamping it away.
- **Regression:** Allocate 500 from an owned eligible account; separately lower balance to 100, exclude it, mark it external, and mark it investment. Assert backed funding, required contributions, overview liquidity, and explicit warnings remain consistent. Include two buckets competing for the reduced funds.

### 5. P1 — API imports are not serialized with other imports or allocation checks

**Follow-up: FIXED IN SOURCE; distributed regression evidence pending.** Shared `ingest` locks the owner before financial reads (`importer.py:285-300`) and refreshes identity-map entries; account/bucket/allocation mutations use the same helper (`routes.py:98,264,273,285,305,334,344`). `locking.py:8-22` requires PostgreSQL READ COMMITTED and uses an owner row lock. `test_review_regressions.py:143-182` checks lock-before-read and stale-session revision/missing-flag refresh. These are SQLite/order tests, not a PostgreSQL simultaneous import/allocation proof; existing PostgreSQL tests cover AI reservations/job claims, not this specific race. The original barrier-based import/allocation test remains the one meaningful missing concurrency regression, not a request to duplicate the existing tests.

- **Locations:** `apps/api/app/routes.py:195-213,297-309`; `apps/api/app/importer.py:239-250,265-294`; contrast `apps/api/app/jobs.py:309-316`.
- The watched-file handler locks the owner; HTTP ingest does not. Different-file HTTP imports can both load the same transaction state, create revisions from stale values, overwrite each other, and race full-snapshot missing flags. The allocation owner lock also cannot protect against an HTTP import changing its observed balance concurrently. Unique constraints only handle identity collisions, not these existing-row races.
- **Fix:** Acquire the same owner lock inside the shared ingestion transaction before reading/updating owner financial state. Define consistent lock ordering with bucket/account operations, and make derived recomputation part of that transaction.
- **Regression:** Real PostgreSQL, separate sessions and barriers: concurrent overlapping revisions/full snapshots must preserve ordered revision history and deterministic missing flags; a concurrent reduced-balance import and allocation must not silently create an apparently backed over-allocation. Exercise HTTP and watched imports together.

### 6. P1 — Decimal conversion happens after XLSX numeric cells have already become floats

**Follow-up: FIXED IN SOURCE.** `importer.py:126-169` safely captures numeric XML lexemes and rejects duplicate archive entries; `:180-182,201-218` resolves the real worksheet target and substitutes original numeric spelling into money/source/identifier inputs. `money` rejects floats/bools (`:59-70`). `test_review_regressions.py:186-218` covers 8-place/boundary/exponent values, exact preserved unknown numeric fields, and `xl/custom/data.xml`; `tests/integration/test_numeric_xlsx.py:12-35` independently checks exact numeric amount/balance/source. Date serials still deliberately use openpyxl epoch/style interpretation. UI number formatting is outside this backend fix.

- **Locations:** `apps/api/app/importer.py:58-67,99-104,137,165,183,214`.
- `openpyxl` decodes non-integral numeric cells into binary floats, then money/source preservation use `str(value)`. This is not an exact conversion from the stored XML decimal and can change accepted 24-digit/8-place monetary values before NUMERIC persistence. The source copy can lose the original numeric representation too. Using Decimal after that conversion does not meet the no-float accounting/source-preservation gate.
- **Fix:** Read raw numeric XML lexemes for money/source preservation with the existing safe ZIP/XML checks, or explicitly reject values beyond a documented precision contract before accepting them; do not silently round.
- **Regression:** Synthetic ZIP/XML workbook containing numeric cells with exact lexemes such as `123456789012345.67` and 8-place decimals near the accepted limit. Assert normalized money and preserved source match XML exactly or that precision loss is explicitly rejected. String-valued amount fixtures alone do not test this.

### 7. P1 — Documented provider/notification environment variables are not wired to adapters

**Follow-up: FIXED IN SOURCE.** `ai.py:124-184,388-405,466-476` consumes documented base URL/key and operator limits, requires explicit persisted consent, and gates production external AI on PostgreSQL before reservation. `notifications.py:188-217,247,314-327` consumes documented notification configuration/token and honors the worker kill switch. `test_ai_jobs.py:655-754,792-857` checks mocked provider forwarding, secret-free consent, operator ceilings, shared scheduled EUR cap, legacy-currency fail-closed behavior, documented ntfy token and per-owner no-fallback behavior. No external provider execution was performed.

- **Locations:** `.env.example:19-22,40-43`; `apps/api/app/ai.py:243-252`; `apps/api/app/jobs.py:338-339`; `apps/api/app/config.py:5-14`.
- The example advertises `AI_PROVIDER_BASE_URL` / `AI_API_KEY`, but the provider forwards neither and these names are not adapter inputs. Likewise the example advertises `NTFY_ACCESS_TOKEN`, while the worker reads `FINSIGHT_NTFY_TOKEN`. Configuring the shipped template can therefore fail provider authentication/routing and omit notification authentication. Environment opt-in booleans are also not persisted policy configuration; document this boundary rather than implying that editing them enables an integration.
- **Fix:** Publish one configuration contract and wire exact secret/base-URL names to the provider/client; retain persisted consent/budget gates. Remove or explicitly mark obsolete example variables. Never expose secret values through settings responses.
- **Regression:** In an isolated environment, configure only documented variable names. Mock LiteLLM/HTTP transport and assert the intended endpoint and synthetic credential are used; never make an external request. Verify missing credentials fail before transmission/reservation where possible.

### 8. P2 — Definite pre-provider failures permanently consume AI concurrency/budget

**Follow-up: FIXED IN SOURCE.** `ai.py:477-515` tracks a conservative transmission boundary and persists `released`/zero charge only for proven pre-provider failures. Released runs do not consume liability/concurrency (`:251-263`); transmitted failures remain uncertain. `test_ai_jobs.py:601-652` checks zero-call input/aggregate/currency/row-limit failures, immediate budget/slot reuse, and cancellation on each side of the boundary. Existing timeout/missing-usage tests continue to assert liability retention.

- **Locations:** `apps/api/app/ai.py:123-129,293-299,317-339`; `apps/api/tests/test_ai_jobs.py:206-218`.
- The durable reservation is committed before graph/input validation. A permitted `max_input_tokens=128` necessarily fails the messages-plus-256-byte envelope before any provider call, yet the generic error handler marks it `uncertain`. With concurrency 1 this blocks every subsequent request indefinitely. No reconciliation route is present. Retaining uncertain liability for actual transmitted/time-out requests is correct; retaining it for a proven zero-call validation failure is not necessary.
- **Fix:** Complete deterministic preflight before reservation, or persist a distinct safely released zero-transmission state. Track the transmission boundary conservatively; never release ambiguous network attempts automatically.
- **Regression:** Full `execute_chat` with a provider spy, too-small input limit, and invalid aggregate/tool output: zero provider calls and no permanent concurrency/budget liability. In contrast, timeout/cancellation after transmission must retain liability and not retry.

### 9. P2 — Proactive worker silently defaults every owner to EUR reports

**Follow-up: FIXED IN SOURCE.** `jobs.py:369-372` no longer supplies notification-derived/default report preferences; `ai.py:693-717` reads the owner's currency/timezone and refuses invalid preferences rather than spending in another zone. `test_ai_jobs.py:757-781` asserts USD/New York report payload and owner-scoped USD aggregates without notification settings. `:784-789` additionally prevents unchanged imports creating changed-import report jobs. EUR AI billing is explicitly distinct from the report's financial currency.

- **Locations:** `apps/api/app/jobs.py:353-364`; `apps/api/app/ai.py:475-500`; `apps/api/app/routes.py:409-410,460`.
- The scheduler supports a currency argument, but the worker never supplies owner settings and always uses its EUR default. USD-only owners can spend opted-in report budgets on EUR zero/count reports rather than their configured currency. The top-level owner timezone is likewise ignored when no notification settings exist.
- **Fix:** Resolve report currency/timezone from owner preferences independently of whether notifications are configured; alternatively require explicit per-currency scheduling consent. Do not combine currencies.
- **Regression:** USD-configured owner with USD-only synthetic activity and no notification settings: queued report requests use USD and the owner's timezone, or explicitly state unsupported scheduling without provider expenditure.

## Remaining concrete defect

### 10. P1 — Nested splits double-count depending on source/group iteration order

- **Current locations:** `apps/api/app/importer.py:347-362`; `apps/api/app/finance.py:59-60,164-180`.
- **Concrete accepted input:** same account/currency/date, rows in order C, B, A; A amount -100 has no parent, B amount -100 references A, C amount -100 references B. Both groups reconcile exactly. The B group is processed first: B becomes `parent`, C becomes `child`. The A group then unconditionally overwrites B as `child`. A remains excluded as `parent`, but B and C are both eligible, yielding expense 200 for a single 100 movement, without a split warning. On reimport, unordered database reads can also change group iteration order.
- **Required fix:** Either explicitly reject/flag nested/cyclic split graphs with a conservative non-double-counting fallback, or reconcile the graph independently of iteration order so intermediate parents cannot be re-enabled as eligible children. This is not a request for expanded alpha functionality: unsupported graphs must not silently return incorrect money totals.
- **Specific missing regression:** Synthetic A/B/C chain above in all six row orders plus reimport/partial import must return exactly 100 once, or an explicit rejected/uncertain result with no parent-and-descendant double count. Include a two-node cycle to verify it is rejected/disclosed. No nested/cycle handling or test was found in current source. This reviewer did not execute a reproducer; the stated result follows directly from role assignments.

## Additional follow-up inspection

- `notifications.py:57-71,278` adds only generic `Click`/`Actions` links from a restricted APP_URL origin, chooses fixed `/insights` or `/imports`, rejects credentials/query/fragment/private paths and malformed ports, and does not attach financial identifiers. `tests/integration/test_notification_links.py:6-15` covers generic destinations plus unsafe/private URLs and header injection. No new security defect established in this helper.
- Raw XML precision and allocation backing were inspected in detail; resolutions above do not rely solely on owners' status reports.

## Reviewed safeguards / do not misclassify as defects

- Inspected HTTP routes authenticate and scope top-level records by owner; child balances/revisions/obligations are reached after an owned-parent check. No concrete cross-owner HTTP read/write bypass was found. Add table-driven two-owner IDOR coverage for every route, including cross-owner allocation account IDs, AI evidence, and notification history; existing isolation coverage is partial.
- Bootstrap has a unique owner slot (`models.py:22`) as its concurrent final guard; it is not merely a check-then-insert vulnerability.
- Mutation CSRF is globally mounted for finance/AI/notification routers (`main.py:15-26`). The origin bug above is an availability/integration defect, not evidence that authenticated CSRF checks are absent.
- AI reserves under a PostgreSQL policy-row lock, commits before transmission, scopes evidence/usage by owner, uses fixed typed aggregate tools, and retains ambiguous billing liabilities. Existing PostgreSQL reservation/claim tests are valuable; do not replace them with SQLite concurrency tests.
- Jobs have durable claims, `SKIP LOCKED`, fenced completion, attempt history, replay-safe flags, and ambiguous-delivery suppression. No generic duplicate-billable-job defect was established. Add process-crash tests at reservation commit, provider return, finding commit, notification `sending`, and final job completion boundaries.
- Historical balances are filtered by observation date, and current allocations are explicitly not subtracted in past-period views (`finance.py:185,202-204`). Current account inclusion/purpose/planned obligations are now explicitly labeled as unversioned (`:160-161`). Historical allocation snapshots remain a disclosed deferred alpha feature, not an unacknowledged subtraction defect.

## In-progress gaps / deployment verification, not established regressions

- `apps/api/Dockerfile` was still absent at the follow-up read. Treat this as **in-progress integration**, not a completed-agent regression or verified Compose build. Main session owns the upcoming live deployment gate.
- Browser/API and Compose smoke have not been run in this review. CI declares these jobs, but declared workflows are not proof of a successful clean deployment. Require the actual clean synthetic Compose run including restore and same-origin browser auth before release.
- **Explicit alpha deferrals, not new blockers for the declared reduced scope:** adaptive/free-form AI, durable HTTP uploads/progress/retry, and historical allocation snapshots. Do not describe these as implemented or call this alpha the full production-ready specification. HTTP imports remain synchronous; watched-file jobs are separately durable. Historical views disclose current unversioned planning/account settings. Fixed-topic aggregate AI is identified as `agent_mode='fixed_topic'` in its settings response.
- This review did not inspect Git content/history or actual export data and is not a privacy/publication sign-off.
