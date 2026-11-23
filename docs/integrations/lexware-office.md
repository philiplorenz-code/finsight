# Lexware Office (formerly lexoffice): import plan

Status: **plan, not built.** Needs the owner's answers in "Open questions" before implementation.

## Recommendation: official API, no browser bot

Lexware Office has a public REST API (`https://api.lexware.io`, docs: developers.lexware.io/docs). It covers
exactly what FinSight would push: vouchers (Belege) and receipt files. A Selenium/Playwright bot that logs into
the web app is the worse route:

| | Public API | Browser bot |
|---|---|---|
| Login | private API key (Bearer), created by the owner under Add-ons → Public API | owner's password + 2FA in FinSight, breaks on every login change |
| Stability | versioned endpoints | breaks with every UI change |
| Duplicates | file checksum dedupe, voucher numbers | must be rebuilt by hand |
| Terms | intended use | likely against the terms of use, risk of a blocked account |
| Secret | API key, revocable on its own | full account password |

So: **API only.** A bot is only worth considering for something the API cannot do (marking vouchers paid or
matching bank transactions, see below), and even then not before the API part runs.

Facts from the API docs (checked 2026-11-23):

- Auth: `Authorization: Bearer <key>`; the old gateway stopped working at the end of 2025, use `api.lexware.io`.
- Rate limit: 2 requests/second across all endpoints, `429` when exceeded → token bucket + backoff in FinSight.
- `POST /v1/files` (multipart `file`, `type=voucher`): pdf, jpg, png, xml, max 5 MB. Lexware runs OCR and creates
  an *unchecked* voucher, returns `id` and `voucherId`; identical files are detected by checksum.
- `POST /v1/vouchers`: `type` (`salesinvoice`, `salescreditnote`, `purchaseinvoice`, `purchasecreditnote`),
  `taxType` (`net` | `gross`), `voucherNumber`, `voucherDate`, `totalGrossAmount`, `totalTaxAmount`,
  `voucherItems[]` (`amount`, `taxAmount`, `taxRatePercent`, `categoryId`), `useCollectiveContact: true` or
  `contactId`, optional `voucherStatus: "unchecked"`.
- `POST /v1/vouchers/{id}/files`: attach the receipt image/PDF to a voucher.
- `GET /v1/posting-categories`: the `categoryId` values (`type` income/outgo); fetched at runtime, never hard-coded.
- `GET /v1/voucherlist` (`voucherType`, `voucherStatus`, date filters, paging up to 250): reconciliation.
- `GET /v1/profile`: `smallBusiness` (Kleinunternehmer) and `businessFeatures` (BOOKKEEPING must be present).
- No endpoint marks a voucher paid or reads bank transactions; `GET /v1/payments/{voucherId}` is read-only.

## What FinSight would send

Only the side business (bookings that match a business rule, see `app/business.py`), never private spending.

**Phase 1: receipts (smallest, most useful).** Receipts/photos linked to a business booking are uploaded with
`POST /v1/files`. Lexware's OCR creates an unchecked voucher; the owner checks it in Lexware as usual.
FinSight stores `lexware_file_id` / `lexware_voucher_id` on the receipt, so nothing is sent twice.

**Phase 2: vouchers from bookings.** For business bookings without a receipt:

- income → `salesinvoice`, category "Einnahmen als Kleinunternehmer" if `smallBusiness`
- expense → `purchaseinvoice`, `taxType: gross`, tax 0 % for a Kleinunternehmer (to be confirmed with the
  owner's tax advisor / a test voucher), collective contact
- `voucherNumber` = `FS-<booking id prefix>` → idempotent, visible in Lexware
- category mapping FinSight category → Lexware posting category, set once on a mapping screen
- created as `unchecked` where the API allows it, so the owner approves in Lexware

**Phase 3: reconciliation.** Per business booking a status: not sent / sent / checked in Lexware
(`voucherlist`). Lexware's own bank connection marks vouchers paid. Webhooks need a public URL, which this
Mac-only setup does not have, so FinSight polls on demand.

## How it works for the owner

1. Create an API key in Lexware Office (Add-ons → Public API) and put it into `.env` as `LEXWARE_API_KEY`.
   FinSight never sees the Lexware password.
2. Business → "Nach Lexware": a preview lists exactly what would be sent (receipt, amount, category, voucher
   number). Nothing is sent without pressing "Senden".
3. After sending: status per booking, link to Lexware.

Safety: the key is only read on the server, never returned by the API or logged; requests carry no private
bookings; dry run is the default; 2 req/s limit enforced; every send is recorded (what, when, Lexware id).

## Open questions for the owner

1. Which Lexware Office tariff? The voucher/bookkeeping API needs the bookkeeping feature (`BOOKKEEPING`).
2. Kleinunternehmer (§ 19 UStG) or with VAT? Decides tax type and categories.
3. Is the business bank account already connected in Lexware? Then phase 2 would duplicate bookings, and
   phase 1 (receipts only) is the right scope.
4. Should Paperless be the archive (all documents) and Lexware only receive business receipts? (Recommended.)
