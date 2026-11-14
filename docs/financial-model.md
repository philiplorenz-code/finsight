# Financial model and interpretation

## Actual cashflow vs plans

An internal EUR 60 transfer from checking to a savings account changes neither net worth nor consumption. It reduces unrestricted funds only when an explicit, non-overlapping allocation reserves those funds. A later external EUR 720 insurance debit is one actual expense. A EUR 720 annual obligation is EUR 60/month in the planning view, not an additional booked expense.

All calculations are currency-specific. Never sum USD and EUR amounts or convert them using a hardcoded rate. Negative balances are liabilities; do not clamp them to zero when calculating observed assets net of overdrafts.

## Balances and coverage

The balance attached to a transaction is an observation at that time. Opening balances, identical booking times, split-row balances and missing accounts can make reconstruction ambiguous. An as-of value must use observations no later than the requested date, not today's latest balance. Imported account totals are **observed account wealth**, not certified total net worth. Investments, property, loans and external accounts may be absent.

The most recent transaction does not establish that a month is complete. Current periods, future entries and incomplete imports must be explicitly labeled. Future-dated rows remain stored but are excluded from completed cashflow until their booking date is reached; this is a date-based assumption, not bank-confirmed settlement.

## Transfers and splits

Source transfer flags take precedence over merchant heuristics. One missing transfer leg is still not consumption, but should trigger a reconciliation warning. Opposite equal amounts alone do not prove common ownership. Unknown external accounts remain unknown.

If split children reconcile to a known parent, count the children or parent once, not both. Unknown or inconsistent split metadata is an error/warning, not permission to silently discard rows. User overrides and source classifications are different records, so corrections can be undone.

## Savings planning

A bucket links real accounts or has virtual allocations. A unit of account currency cannot fund two buckets simultaneously. Account balances are assets; bucket allocations are restrictions on those assets, not new assets. A bucket withdrawal is only consumption if the underlying transaction is external.

For a future obligation, subtract existing allocated funds and explicitly scheduled contributions from the expected cost, then divide the remaining deficit by available monthly contribution periods. Do not subtract an unscheduled wish twice. Monthly normalization uses known recurrence periods; unknown recurrence is not assumed monthly.

## Explainable indicators

- Monthly surplus: completed external income minus completed external expense.
- Savings rate: surplus / positive external income; undefined when income is zero.
- Fixed cost ratio: normalized known recurring obligations / positive income; coverage may be incomplete.
- Emergency fund coverage: unreserved liquid funds / representative monthly essential costs; requires explicit essential-cost classification.
- Debt service: identifiable principal and interest outflows, not all negative account balances.
- Volatility: historical variation of comparable completed periods, not future rows.

Do not fabricate missing indicators or turn incomplete data into an opaque financial score. Report evidence, observation period and limitations with each finding.
