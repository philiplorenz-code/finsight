# Changelog

## 0.1.0 — Initial implementation

- FinSight monorepo, self-hosted deployment and English operational documentation.
- Target requirements and acceptance stories recorded before implementation.
- Optional read-only remote MCP: official SDK Streamable HTTP, owner-approved OAuth/PKCE, independent scopes, rotating/revocable credentials and connection management.
- Twelve bounded finance tools, canonical explorer-compatible views/evidence, three semantic resources and five reusable MCP workflow prompts.
- Deployed synthetic OAuth/protocol/browser-consent/restore rehearsals and real PostgreSQL token replay/concurrency regressions; live ChatGPT linking remains an operator verification task.
- See `docs/release-status.md` for tested features, unmet criteria and deployment caveats.

## Unreleased

- Jahresrückblick (`/year`, `GET /api/reports/yearly`): income, spending, categories, merchants and months next to the year before; a running year is compared with the same days of the previous year, with a hint when data starts later.
- Kündigungshelfer: customer number per contract, cancellation letter generated in the browser (copy, print/PDF), calendar file for the deadline, and "als gekündigt markieren", which freezes the end date and stops deadline reminders (migration `0024_contract_cancellation`).
- Docs: switching the AI provider to OpenAI so receipt photos can be read.

- Paperless-ngx: local compose project (`infrastructure/paperless`), receipts can be archived there, booking details list matching Paperless documents, settings show the connection (migration 0023).
- Plan for importing the side business into Lexware Office via its public API (`docs/integrations/lexware-office.md`).

- Aufräumen: select several merchants and sort them into one category, or accept all suggestions at once.
- Early budget warnings: plan items at 90 % of their target, or projected above it after the first week, show under "Jetzt wichtig" and send the plan notification once per month.

- Aufräumen: bookings without a useful category, grouped by merchant with a suggested category (same merchant's usual category or keyword hint); one click creates a category rule for past and future bookings.
- Global search in the top bar (Cmd/Ctrl+K): merchants, bookings, contracts and accounts incl. IBAN, full-screen on phones.
- Needs attention: one list on the overview for cancellation deadlines within 30 days, overdue open items, payments that could settle an open item and plan items over target (`GET /api/attention`).
- Reminder notifications (`reminder` event): 14, 7 and 2 days before a cancellation deadline and when an open item falls due; generic text, deduplicated, checked at most hourly.

- Cash book (`/cash`): from a chosen start date, ATM withdrawals (category Bargeld) count as moving money into the wallet and logged cash spending counts instead, with its own category, in overview, baseline and plan vs. actual; calculated wallet balance; quick entry made for phones. Migration 0022.

- Open items (`/open-items`): money someone owes you or you owe, with due date and note; a matching payment after the start date is suggested for one-click settlement. Migration 0021.
- Side business on phones: clients as cards with month chips instead of a 13-column table. Footer in German.

- Concrete instead of averaged: planning uses the latest month's salary when pay changed; the wishlist shows the last complete month (salary, side business, spending, surplus) and a month-by-month table instead of averages. All averages moved to a new page **Durchschnitte** (`/averages`).
- Bank detection knows bunq (German IBANs, BLZ 37019000), Trade Republic and Solaris; accounts with an unknown bank are checked again on the next listing.
- Phones: transactions, coming up and plan items become compact cards below 640 px, the period picker scrolls sideways, header buttons wrap in a row, the AI banner stacks, tap targets at least 32-36 px.

- Accounts show their IBAN (from the export's Referenzkonto, filled for existing accounts on the next account listing) with a copy button. Migration 0020.
- Current salary: when pay changed in the last three months, wishlist, forecast, health check and analyst use the median of those months instead of the twelve-month average (with a notice).
- Dependency updates (bundles the open Dependabot PRs): Node 26 and nginx-unprivileged 1.31 images (Python stays 3.12: no 3.15 wheels for zstandard yet); actions/checkout, setup-python, setup-node v7, gitleaks-action v3; lucide-react 1.75, jsdom 31, vitest 5.1.1, user-event 14.6.12, @types/node 26; minimum versions alembic 1.20.1, argon2-cffi 25.1, python-multipart 0.0.33, uvicorn 0.54, SQLAlchemy 2.1.8.

- Cancellation deadlines: store term end, notice period and renewal per contract (contract detail); the contracts page lists the next last day to cancel with a countdown, and deadlines appear under coming up (`/api/contract-terms`). Migration 0019.

- Monthly close page (`/report`, `GET /api/reports/monthly?month=`): income, expenses, surplus and savings rate against last month and the six-month average, money at month end, categories with change vs. average, biggest expenses, plan vs. actual, anomalies and highlights; print-friendly for PDF.
- AI analyst planner: two more typed tools (max. 5 steps): `contract_focus` (top running contracts with rhythm and price change, names only with consent) for contract and savings questions, `tax_check` (side-business VAT and income-tax reserves against tax pots) for income and forecast questions. Tool inputs are kept server-side unless a tool selects them.
- Wishlist redesign: "What works when" timeline on top (priority order, traffic light, expected and cautious date, how far free cash already reaches), compact wish cards with details folded, simulator and plan chart below, calculation basis, income and business folded away.
- iPhone: installable as a home-screen app (manifest, icons, standalone safe areas, no input zoom), Sankey labels fit small screens.
- Import from iPhone via the share sheet: import-only device keys (shown once, stored as SHA-256, revocable, 30 uploads/hour) and `POST /api/device/import` (bearer key, no cookies) used by an iOS Shortcut; setup guide under Settings. Migration 0018.
- Docs: secure phone access via Tailscale HTTPS (`docs/operations.md`).

- Receipts: photograph or upload a receipt (JPEG/PNG/WebP/HEIC, max. 8 MB, stored only in the upload directory), read it with the configured AI model (same consent, budget and settlement as the analyst; the model must accept images) or enter items by hand, automatic match to the bank booking, and analysis by item category and top items with price development. Migration 0017. Refs #84.
- Side business gross to net: gross income → VAT (19/7/0 %) → net revenue → business expenses → EBITDA (= EBIT) → tax adviser → profit before income tax → income-tax reserve → what is left, per month and year with net margin; required reserves against actual transfers into tax pots (Umsatzsteuer/Einkommensteuer/Steuerberater) and payments from them.
- Contracts page redesign: monthly/yearly total, clickable cost bars per kind, search, kind filter, sort (cost, next charge, name), price-increase filter and contracts as cards grouped by kind; stopped contracts folded away.
- Learn from corrections: after changing a booking's category the detail view offers to save it as a merchant rule for all bookings.
- Forgotten password: `scripts/reset-password.sh` (runs `python -m app.admin reset-password` in the API container, prompts without echo, ends all sessions).
- Net worth page lists money held in trust for others (accounts with a share below 100 %, e.g. tax pots or family money) with balance and monthly inflow.

- Side business page: income per client (business income rules) and business expenses per month, months without payments, reserve suggestion and an EÜR-style CSV preview (`GET /api/business/overview`, `GET /api/business/euer.csv`).
- Merchant profile: click a merchant in the transaction list for monthly spending (zoomable), categories, accounts, contract match and recent bookings (`GET /api/merchants/profile`).
- Savings goals: buckets with target and due date get a traffic light comparing the needed monthly rate with standing orders into the backing accounts, plus the projected amount at the due date.
- Anomaly watch: possible double debits, unusually high amounts, new recurring payments and price increases (`GET /api/anomalies`), on the overview and insights page; `anomaly` notification after imports.
- What-if simulator on the wishlist page: salary, side business, rent and extra savings sliders update surplus, cash in 12 months and wish timing instantly.
- Sankey diagram of regular monthly flows (income sources → your money → categories, tax reserve, surplus) on the analysis page (`GET /api/flows`).
- Transaction list shows account names instead of IDs.
- Receipts: photograph or upload a receipt (JPEG/PNG/WebP/HEIC, max. 8 MB, stored only in the upload directory), read it with the configured AI model (same consent, budget and settlement as the analyst; the model must accept images) or enter items by hand, automatic match to the bank booking, and analysis by item category and top items with price development. Migration 0017. Refs #84.

- Coming up: `GET /api/upcoming?days=` lists expected contract debits (with account), standing orders into pots and expected pay for the next days; shown on the overview (14 days) and the plan page (30 days).
- Forecast: `GET /api/forecast?months=` projects cash and net worth (expected and cautious) month by month from the baseline surplus, loan amortisation (principal repaid, payment freed after payoff) and flat assets; chart with zoom on the net-worth page.

- Overview and its cash-flow trend place month-end pay in the following month when the income rule sets `shift_from_day` (e.g. salary on the 29th counts for next month).
- Overview balance tile shows your share (`observed_mine`) and lists money held for others (`held_for_others`) instead of the gross sum; available liquidity uses the owner share.
- Dev: Vite proxy target configurable via `FINSIGHT_API_PROXY`.
- Transaction details show the money flow: from which account to which (own account, and for transfers the matching own counter account; otherwise the counterparty with the last four IBAN digits).
- Account-backed savings buckets: choose the backing account when creating; the target (or the current balance) is earmarked on it.
- Balance history dialog shows a chart; time charts (balance history, overview cash flow) zoom Grafana-style by dragging across a range, double-click resets.
- Transaction details show the money flow: from which account to which (own account, and for transfers the matching own counter account; otherwise the counterparty with the last four IBAN digits).
- Account-backed savings buckets: choose the backing account when creating; the target (or the current balance) is earmarked on it.
- Balance history dialog shows a chart; time charts (balance history, overview cash flow) zoom Grafana-style by dragging across a range, double-click resets.
- Consistent language: backend codes (account purpose and ownership, rhythms, import and run states, confidence, notification events, wish and finding status) are shown through one label table (`lib/labels.ts`) in German or English instead of raw English codes.
- Overview and its cash-flow trend place month-end pay in the following month when the income rule sets `shift_from_day` (e.g. salary on the 29th counts for next month).
- Overview balance tile shows your share (`observed_mine`) and lists money held for others (`held_for_others`) instead of the gross sum; available liquidity uses the owner share.
- Dev: Vite proxy target configurable via `FINSIGHT_API_PROXY`.
- Bank/provider per account: detected from the IBAN's bank code (e.g. DKB, N26, ING, Sparkasse, Volksbank, bunq, Revolut) or the name (PayPal), only the provider name is stored. Set or clear it manually; filter accounts and transactions by bank (`provider` query parameter, `GET /api/account-providers`). Migration 0016.

- Spending paid straight from savings pots (e.g. groceries, fuel, holiday pots) now counts in the baseline used by wishlist, health check and analyst; pot interest and refills are not income.
- New account purpose `mirror` (e.g. PayPal): its balance counts, its bookings are excluded from spending, overview and plan actuals because the bank account already shows them. Suggested automatically for PayPal-like account names.

- Plan vs. actual weights each booking by the owner share that applied on its booking day (e.g. 50 % while an account was shared), using the account setting history.

- Plan vs. actual (Soll/Ist): monthly targets per item (pot and/or category), actuals from the pot plus the same category on other accounts, traffic light on the overview, six-month history, projection for the running month, `plan_exceeded` notification, and an overview of standing orders into pots and recurring debits.

- Cash on hand, reserve and usable cash now count only the owner's share of each account, so money held for others (tax pots, family) no longer inflates free money.

- German texts for all backend warning notices on imports, transactions, buckets, contracts, net worth and wishlist via one shared table (`lib/warnings.ts`); unknown messages fall back to English.

- AI analyst: bounded adaptive planner (max. 4 typed deterministic tools, 2 s budget; focus category, ranked savings levers, data caveats). The chosen steps are shown with each answer and stored as evidence; no model-chosen tools or SQL.

- As-of views: `GET /api/as-of?date=` reconstructs account balances, the settings that applied then (account change history, migration 0014; an "unknown" ownership is treated as undecided, not as a past fact) and earmarks from the allocation history. Never uses later observations; flags missing opening balances, conflicting same-day observations, old observations and inactive accounts. Panel on the net worth page. Closes #20.

- AI analyst: deterministic intent plan (a question about debt only sends the sections it needs), health metrics and payoff scenarios in the context, and `GET /api/ai/findings` with ranked structured findings (severity, confidence, monthly impact, evidence) computed without a model; shown in the analyst panel. Refs #19.

- Durable imports: background uploads are kept (private directory, named by hash, removed after success, purged after 7 days) so an import interrupted by a crash or restart resumes at start-up, and failed imports can be retried without re-uploading (`POST /api/imports/{id}/retry`). Set `FINSIGHT_UPLOAD_DIR` to move the directory (default `/data/app/uploads`). Closes #18.

- Administration: manage dialog for buckets (rename, delete with confirmation, edit/delete obligations), append-only allocation history (migration 0013), source revision diffs per booking. Refs #22 (retention/purge controls are still open).

- Financial check on the overview: savings rate, emergency-fund months, debt-service ratio and spending volatility (each stays empty with a reason when its inputs are missing), a 6-month free-cash forecast (expected and cautious) and alerts for underfunding, low emergency fund, negative surplus, volatile spending, category anomalies and price increases of recurring contracts. Closes #21.

- Net worth history now includes holdings (dated value snapshot whenever a value is set or changed, migration 0012), an amortisation chart per debt (monthly interest, cent rounding, payment below interest never repays) and a wishlist panel showing the surplus once a debt is repaid. Closes #36.

- Operations: disk-space warning on the overview (`GET /api/system/disk`), `scripts/scheduled-backup.sh` with retention and a free-space guard, `docs/operations.md` with pruning and cron/launchd recipes. Closes #40.

- CI: Playwright browsers are cached and the install retries when apt mirrors are unreachable (shared composite action). Closes #39.

- Searchable account picker (transaction filter and income rules); accounts with the same name get a short id suffix. Closes #38.

- Import coverage: each import summary lists per account the rows, first/last booking and previous row count, and names accounts whose history shrank (file starts later or rows are missing). The watched folder imports files named like "Alle Buchungen" as full snapshots (`FINSIGHT_WATCH_FULL_SNAPSHOT=auto|true|false`). Closes #48.
- New accounts after an import: a reminder on the overview, accounts and imports pages and a one-step dialog to classify them (ownership, purpose, include) with suggestions from name, balance and usage; import summaries report `new_accounts`. Closes #49.
- Category rules (pattern, income/expense, account) assign categories to bookings without touching imported data; manual corrections win. Review list for automatically detected transfers where a pair can be rejected for good (migration 0011). Closes #43.
- Settings: change password and e-mail (current password required, minimum 12 characters, rate limited, other devices are signed out after a password change). Closes #44.
- Imports: the upload form imports in the background (immediate response, status updates automatically, interrupted runs are marked failed after 30 minutes) so a large export no longer blocks the web process; header normalisation is cached (about 1.2 million calls per 13k-row export); `scripts/bench-import.py` profiles the importer. A 13k-row re-import of a real export measured about 7 s on PostgreSQL. Closes #47.
- AI analyst: free-form questions about your finances on the Insights page, answered from rounded aggregates of your own analysis (never single bookings; names only on request) with a "what is sent" preview; budgets and consent reuse the existing AI controls. Progress on #19.
- Tests: the synthetic workbook helper now produces byte-identical files for identical rows (zip and document timestamps pinned); the duplicate-import test failed rarely when two uploads straddled a clock boundary.
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
