# Changelog

## 0.1.0 — Initial implementation

- FinSight monorepo, self-hosted deployment and English operational documentation.
- Target requirements and acceptance stories recorded before implementation.
- Optional read-only remote MCP: official SDK Streamable HTTP, owner-approved OAuth/PKCE, independent scopes, rotating/revocable credentials and connection management.
- Twelve bounded finance tools, canonical explorer-compatible views/evidence, three semantic resources and five reusable MCP workflow prompts.
- Deployed synthetic OAuth/protocol/browser-consent/restore rehearsals and real PostgreSQL token replay/concurrency regressions; live ChatGPT linking remains an operator verification task.
- See `docs/release-status.md` for tested features, unmet criteria and deployment caveats.

## Unreleased

- Analysis page with seven charts: income by source, income vs outgoings, monthly surplus, surplus rate, cumulative surplus, spending by category and largest payees.

- Income source rules: split income into employment (Bauhaus), business and unassigned, with per-source averages and weak-quarter values on the wishlist.
- Tests: the concurrent MCP owner-isolation test now uses a file-backed SQLite database; the shared single connection caused rare CI failures.

- Wishlist: add wishes with price, priority, due date and running cost; deterministic affordability verdicts (affordable / save up / tight / not now) using a conservative (lower quartile) and an expected (12-month average) surplus, cumulative in priority order, with explicit assumptions and no currency mixing.
- Baseline derives income, consumption and tax from owned accounts, excluding transfers, savings categories and configured own-name transfers; usable cash respects a configurable reserve.
