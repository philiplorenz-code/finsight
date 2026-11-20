# Release verification and limitations

FinSight is an **early 0.1 implementation**, not a claim that every target story or production acceptance criterion has passed. The specification describes the intended product. This record distinguishes executable verification from deferred functionality. Verification date: 2026-11-14.

## Published project and verification

- Public Apache-2.0 repository: <https://github.com/philiplorenz-code/finsight>.
- The [baseline CI run](https://github.com/philiplorenz-code/finsight/actions/runs/43637165777) passed backend/PostgreSQL tests, dependency audits, frontend build/unit/browser tests, publication checks and a clean Compose/browser/backup/restore rehearsal. For any subsequent revision, inspect its own [CI result](https://github.com/philiplorenz-code/finsight/actions/workflows/ci.yml); a baseline pass is not evidence for an untested update.
- Final local suite including the MCP increment: **377 Python tests and 66 subtests passed**, with the isolated PostgreSQL concurrency suites enabled. Includes code/refresh replay races, owner isolation, permission step-up, exact MCP routing and migration round-trip/schema checks.
- Frontend: production build, **37 unit tests and 75 browser tests passed**; one desktop-only skip for the mobile navigation test is intentional. Populated charts and long OAuth callback URLs pass mobile-width checks.
- Python and npm audits reported no known vulnerabilities at verification time. That is not a security certification.
- Final non-root Compose images started successfully and migrated PostgreSQL to `0002_mcp_oauth`. Real same-origin browser auth, cookie/CSRF protection, synthetic import/idempotency/transfer totals and dashboard rendering passed through nginx.
- Actual synthetic backup/restore after the MCP migration passed login, reconciliation and browser checks. Runtime MCP was enabled temporarily for a separate rehearsal and then returned to its default disabled state.

## MCP increment

Implemented: official SDK Streamable HTTP at `/mcp`, explicit owner OAuth/PKCE consent, independent read/transaction scopes, short-lived hashed credentials, rotating refresh tokens, family revocation on correctly bound replay, disabled-by-default operation and UI connection revocation. Twelve typed read-only tools, three static resources and five protocol-native workflow prompts support bounded analyses with explicit views, filters, currency, evidence and uncertainty. Canonical evidence links resolve to the same predicates in the authenticated transaction explorer.

The deployed synthetic protocol rehearsal passed discovery, registration, PKCE exchange, actual overview totals, resource reads, prompt retrieval, scope step-up challenges, refresh rotation and revocation. The real browser rehearsal approved aggregate-only access without the optional transaction checkbox, then revoked the connection and observed HTTP 401 at the MCP endpoint. No external model or ChatGPT service was called.

**Live ChatGPT linking and public HTTPS ingress have not been verified.** They require an operator-controlled reachable HTTPS deployment and an eligible client/account; tracked in [#23](https://github.com/philiplorenz-code/finsight/issues/23). Protocol compatibility is not certification by OpenAI. Client support for prompts/resources varies. Public deployments must deliberately configure trusted proxy CIDRs and perimeter controls; default peer-based OAuth limits can be exhausted by traffic sharing a proxy/NAT. See [MCP security review](mcp-security-review.md), [setup](mcp.md) and [configuration](deployment/configuration.md).

## Privacy evidence

The private workbook was inspected and parsed locally without printing values. A temporary private database import/reimport preserved all 13,213 records and detected duplicates; that database was removed. Exact XML Decimal parsing was separately reverified. No real rows were used in fixtures, screenshots, remote requests or Git.

The publication gate scans working/index content and all historical Git objects, including deleted content. Independent Gitleaks scanning retains its default detector rules and a narrowly bounded non-secret example allowlist. `.env`, source workbooks, runtime files and backups remain ignored. Exact synthetic screenshot hashes are explicitly approved in `screenshots/reviewed.json` after visual inspection. These checks reduce risk; they do not replace protected hosting, backup encryption or an independent audit.

## Explicitly deferred or incomplete

- Browser uploads run in the background and are retained until the import completes (resume after restart, retry button); there is no percentage progress, only status. Watched-folder jobs are durable.
- Internal AI is a bounded fixed-topic aggregate explainer, **not adaptive/free-text financial chat**. Structured adaptive planning, broader reasoning and complete proactive insight coverage remain deferred. External MCP clients can perform their own analyses, but that does not complete FinSight's internal AI backlog. [#19](https://github.com/philiplorenz-code/finsight/issues/19)
- Observed balances are not complete net worth. Multiple observations on one day can be ambiguous; historical account settings/plans are not versioned, and historical allocation snapshots are absent. Negative/missing/stale/unknown ownership observations remain visible limitations. [#20](https://github.com/philiplorenz-code/finsight/issues/20)
- Complete forecasts, volatility, debt-service ratios, emergency-fund coverage and all proactive alert producers are not implemented. Investment purchases are not comprehensively separated from consumption unless source/account classifications establish their semantics. [#21](https://github.com/philiplorenz-code/finsight/issues/21)
- Bucket lifecycle, obligation editing, allocation history, transaction revision-diff UI and retention administration are not all exposed. Some backend warnings remain English in the German interface. [#22](https://github.com/philiplorenz-code/finsight/issues/22)
- Nested, cyclic and self-referencing split graphs are **rejected atomically**, not supported as complex accounting structures. Malformed graphs never silently double-count.
- Live paid AI providers and ntfy delivery were not exercised; controlled adapters and synthetic failure/consent/budget tests were used. Operator-maintained EUR prices are estimates; external MCP client model costs are outside FinSight's AI caps.
- Single-owner deployment only. No independent penetration test, formal accounting audit, public production TLS review or complete crash-at-every-boundary proof has been performed.

Outstanding product work is tracked in the [v0.2 milestone](https://github.com/philiplorenz-code/finsight/milestone/1). Do not describe this alpha as the complete production-ready specification.
