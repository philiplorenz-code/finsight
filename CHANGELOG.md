# Changelog

## 0.1.0 — Initial implementation

- FinSight monorepo, self-hosted deployment and English operational documentation.
- Target requirements and acceptance stories recorded before implementation.
- Optional read-only remote MCP: official SDK Streamable HTTP, owner-approved OAuth/PKCE, independent scopes, rotating/revocable credentials and connection management.
- Twelve bounded finance tools, canonical explorer-compatible views/evidence, three semantic resources and five reusable MCP workflow prompts.
- Deployed synthetic OAuth/protocol/browser-consent/restore rehearsals and real PostgreSQL token replay/concurrency regressions; live ChatGPT linking remains an operator verification task.
- See `docs/release-status.md` for tested features, unmet criteria and deployment caveats.

## Unreleased

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
