# Finanzguru XLSX ingestion

FinSight targets the 29-column single-sheet Finanzguru export. Real exports are private and must stay outside Git. The locally provided workbook was inspected for format only; no actual account or transaction values are included here.

## Source columns

```text
Buchungstag
Referenzkonto
Name Referenzkonto
Betrag
Kontostand
Waehrung
Beguenstigter/Auftraggeber
IBAN Beguenstigter/Auftraggeber
Verwendungszweck
E-Ref
Mandatsreferenz
Glaeubiger-ID
Analyse-Hauptkategorie
Analyse-Unterkategorie
Analyse-Vertrag
Analyse-Vertragsturnus
Analyse-Vertrags-ID
Analyse-Umbuchung
Analyse-Vom frei verfuegbaren Einkommen ausgeschlossen
Analyse-Umsatzart
Analyse-Betrag
Analyse-Woche
Analyse-Monat
Analyse-Quartal
Analyse-Jahr
Buchungs-ID
Referenz-Original-ID
Split-Typ
Tags
```

Unknown columns remain private source metadata. A preview reports structure, counts and warnings, not raw spreadsheet contents. Source references, names and descriptions are sensitive even if they are not IBANs.

## Safety

Accept only `.xlsx` uploads within configured byte limits. Check archive entries, total decompressed size, suspicious compression ratios, XML parser safety, worksheet/column/row caps and formula/external-link/macro content. Never execute spreadsheet formulas or open arbitrary filesystem paths from upload filenames. Parser errors must not echo cell values.

These controls reduce risk but are not a universal defense against every malformed workbook. Keep parser dependencies updated and limit container resources. A workbook that violates limits is rejected as a whole rather than partially committed without explanation.

## Re-import semantics

- SHA-256 identifies an identical file; replay returns the original successful import.
- Stable account reference plus booking ID identifies a transaction independently of the display name.
- Missing booking IDs need conservative fallback matching with visible ambiguity warnings; date, amount and merchant alone are insufficient proof.
- Changed source rows retain prior source revisions. Overrides remain separate.
- A partial export must not delete earlier history. Missing-row detection requires explicit full-snapshot intent and is advisory.
- Split parents and children must reconcile before excluding a duplicate parent from aggregates.
- Source-flagged internal transfers do not become spending just because their other side is absent.
- Future-dated rows remain stored and are excluded from completed movements by booking date, with limitations disclosed.

## Reconciliation

Review import counts, date coverage, fallback-identity warnings, unmatched transfers, ambiguous splits and account balance observations. Imported names are not reliable stable identifiers. Changes in balance are not necessarily explained by the visible export interval, especially when opening coverage is missing.

Upload processing and retry behavior of this release are described in `docs/release-status.md`; do not infer background progress or retained-file retry support from the target specification.
