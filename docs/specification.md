# FinSight specification

**FinSight — Your money. Clearer insights.** Independent, Apache-2.0, self-hosted personal finance intelligence. Not affiliated with Finanzguru. German UI by default; English available. Default EUR and Europe/Berlin; never combine currencies without explicit exchange rates.

## Release contract

This specification describes the target product, not a claim that every feature is implemented. `docs/stories.md` tracks delivery and acceptance. A release must distinguish verified functionality, unverified deployment behavior and deferred work.

## Actors and boundaries

- Owner: securely bootstraps the installation, imports data, adjusts classifications and operates optional integrations.
- Analyst: authenticated owner viewing deterministic metrics and evidence-backed AI explanations.
- Worker: processes persistent jobs with bounded retries and exclusive claims.
- External AI / ntfy: optional third parties; disabled until explicitly configured. No telemetry.

## Functional requirements

1. **Identity:** single-owner initial release, user-owned rows for future isolation; bootstrap secret; modern password hashing; server-side expiring sessions, CSRF protection and rate limits.
2. **Ingestion:** validated XLSX only, compressed/decompressed/resource limits, no formula evaluation, preview, persistent processing/history, retry, reconciliation and unchanged-file idempotency. Preserve all 29 verified columns and unknown fields separately from normalized values. Booking/account identity first, documented conservative fallback. Preserve revisions and flag missing records without destructive deletion. Do not assume each export is a full snapshot.
3. **Accounting:** Decimal/NUMERIC, date separate from timestamp, pending future rows excluded from completed movements. Transfers (including one-sided source flags) excluded from consumption; ambiguous ownership disclosed. Splits reconcile or warn, never silently count parent and children. Latest observed balances are not necessarily complete net worth.
4. **Explorer:** pagination, search, date/account/category/amount/merchant/transfer/contract/tag filters, detail, reversible overrides, source values retained.
5. **Accounts:** stable source identity independent of editable name; inclusion, purpose, ownership, inactive status, balance history with incomplete-coverage warning.
6. **Buckets:** real and virtual buckets, many-to-many account linkage, explicit allocations, no reuse of funds, multiple obligations, funding progress, due dates, scheduled contributions and required monthly funding. Contributions are not expenses; annual obligations are normalized separately from actual cashflow.
7. **Analytics:** currency-separated income/expense trends, account balances, category breakdown, savings rate, monthly surplus, fixed obligations, emergency coverage, debt-service data limitations, volatility, forecasts and historical as-of views. Filters include custom and named periods; incomplete months labeled.
8. **Contracts:** source contract metadata plus confidence-labeled inferred recurrence, periodicity, annualized cost, next charge, price changes and evidence.
9. **AI:** LangGraph bounded read-only typed tool loop, LiteLLM-compatible provider, no arbitrary SQL; minimized aggregate outgoing data; external consent, allowlist/pricing, conservative atomic budget reservation, settlement, timeout/iteration/tool/token/concurrency limits and usage dashboard. Missing provider billing data fails closed. Proactive reports require separate opt-in and budget. Findings carry resolvable evidence and lifecycle state.
10. **Jobs/notifications:** persistent PostgreSQL jobs, safe concurrent claims, retries/history, watched stable files without deletion; local-time reminders/quiet hours, stale-import suppression, weekly/monthly/report-ready/anomaly triggers; ntfy generic messages, configurable server/auth, notification history.
11. **Interface:** responsive accessible React/TypeScript dashboard, light/dark themes, DE/EN, import progress, empty/error/loading states and clear uncertainty.
12. **Operations:** Compose, migrations, non-root services, health checks, persistent volumes, secrets in environment, backup/restore, CI/dependency/secret scans, documented retention and disclosure policy.
13. **MCP connectivity:** optional standard Streamable HTTP MCP endpoint for external assistants; disabled by default; OAuth 2.1 authorization-code + PKCE, explicit owner consent, revocable least-privilege read-only scopes, bounded typed finance tools, resolvable evidence and view/filter descriptors. Native MCP resources document semantics and native prompts encode reusable analysis workflows ("skills"). No arbitrary SQL, writes, file reads, secret/source-reference exposure or automatic data transmission. External-client model charges are outside FinSight's internal AI budget. ChatGPT compatibility requires a reachable HTTPS deployment and supported client capabilities; do not claim untested live-client certification.

## Non-functional acceptance gates

- No real export, extracted private values, credentials or PII in Git, fixtures, logs, screenshots or provider requests without consent.
- All finance calculations use Decimal; API money values are strings.
- Authorization is enforced on every query and mutation in backend services.
- No public push before full tracked-content and history privacy inspection.
- Automated unit/integration/browser tests; clean Compose smoke test required before claiming production deployment verified.
- Large 13,213-row synthetic import regression; real workbook local validation outputs counts/structure only.

## Verified input inspection

Local ZIP/XML inspection confirmed one worksheet, 29 exact supplied headers, 13,213 records, approximately 20.5 MB decompressed XML. Cells use numeric, inline-string and blank storage. No private cell values were printed or copied into the repository. The original workbook remains ignored outside source control.

## Architecture and implementation contracts

Monorepo: `apps/api` FastAPI + SQLAlchemy 2 + Alembic/PostgreSQL; `apps/web` React/Vite/TypeScript; one PostgreSQL-backed worker. Frontend uses same-origin `/api` via reverse proxy. API prefix `/api`; cookie sessions; money serialized as decimal strings; authenticated routes user-scoped. Frontend must handle unavailable optional integrations honestly.

Core routes: `/health`, `/auth/status`, `/auth/setup`, `/auth/login`, `/auth/logout`, `/auth/me`, `/overview`, `/accounts`, `/transactions`, `/imports`, `/imports/preview`, `/buckets`, `/contracts`, `/findings`, `/ai/chat`, `/ai/usage`, `/settings`, `/notifications/test`. API owner publishes OpenAPI; frontend adapts to actual schemas.

## Financial definitions

Actual cashflow = completed external income less completed external expense, per currency. Internal transfers change account liquidity but not consolidated net worth. Observed net worth = included owned account balances at available observations; not a full asset valuation. Available liquidity = observed liquid assets less disjoint funded allocations; negative balances remain negative. Monthly planned obligation = annualized recurrence/12, not another transaction. Required contribution = max(0, expected debit - available bucket funds - explicitly scheduled future contributions) / remaining contribution periods. Missing balances, ambiguous splits and incomplete coverage must be visible.
