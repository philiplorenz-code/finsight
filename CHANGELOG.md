# Changelog

## 0.1.0 — Initial implementation

- FinSight monorepo, self-hosted deployment and English operational documentation.
- Target requirements and acceptance stories recorded before implementation.
- Optional read-only remote MCP: official SDK Streamable HTTP, owner-approved OAuth/PKCE, independent scopes, rotating/revocable credentials and connection management.
- Twelve bounded finance tools, canonical explorer-compatible views/evidence, three semantic resources and five reusable MCP workflow prompts.
- Deployed synthetic OAuth/protocol/browser-consent/restore rehearsals and real PostgreSQL token replay/concurrency regressions; live ChatGPT linking remains an operator verification task.
- See `docs/release-status.md` for tested features, unmet criteria and deployment caveats.

## Unreleased

- Contracts: recurring payments (monthly to yearly, tolerating a missing booking) are detected and classified as insurance, housing, loan, subscription, utility or other; totals per class, cancellation/renegotiation checklist with price increases, stopped contracts, and confirm / dismiss / rename / reclassify decisions that survive re-imports (migration 0010). Closes #37.
- Data quality: per-account report of empty months, unusually quiet months and accounts that end earlier than the rest (imports page); gaps in the analysis window lower the wishlist confidence and add a hint. Closes #42.
- Balances: an account that appears in a full-snapshot import counts as current as of that import, so a fresh export no longer leaves most accounts "stale"; the upload form has a "full export" option (on by default; migration 0009). Closes #46.
- Business: spending rules (merchant, category, account) separate business expenses from private consumption; the conservative scenario assumes business income at its weak-quarter value; tax reserve suggestion from business profit (confirmed by you, never applied silently); business chart on the analysis page (migration 0008). Closes #41.
- Analysis: savings potential (fixed vs variable spending, category trend of the last 3 months against earlier, recurring costs with price changes) as plain arithmetic on your own data.
- Net worth page: accounts plus manually tracked assets and debts (car, loan, property, depot), each split into your share and the part that belongs to others, monthly debt service, payoff date and a balance history (migration 0007). Overview data notes are in German and the permanent coverage notes are folded away.
- Transfers: money moved between your own accounts is detected by amount/date matching (also after each import) so it no longer counts as income or spending; "Umbuchungen prüfen" on the transactions page previews and applies it (migration 0006).
- Income rules: optional "from day X count in the next month" so month-end salary is attributed to the month it pays for (migration 0005).
- Web: upgrade vite 6 → 8 together with @vitejs/plugin-react 4 → 6 (plugin-react 4 does not support vite 8); build, typecheck and unit tests pass.
- Wishlist saving-plan chart: expected and conservative cash path over 24 months against the cumulative price of open wishes.

- Analysis page with seven charts: income by source, income vs outgoings, monthly surplus, surplus rate, cumulative surplus, spending by category and largest payees.

- Wishlist: baseline warnings, assumptions and confidence are shown in German in the German UI.
- Income source rules: split income into employment (Bauhaus), business and unassigned, with per-source averages and weak-quarter values on the wishlist.
- Tests: the concurrent MCP owner-isolation test now uses a file-backed SQLite database; the shared single connection caused rare CI failures.

- Wishlist: add wishes with price, priority, due date and running cost; deterministic affordability verdicts (affordable / save up / tight / not now) using a conservative (lower quartile) and an expected (12-month average) surplus, cumulative in priority order, with explicit assumptions and no currency mixing.
- Baseline derives income, consumption and tax from owned accounts, excluding transfers, savings categories and configured own-name transfers; usable cash respects a configurable reserve.
