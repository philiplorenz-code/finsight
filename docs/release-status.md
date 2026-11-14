# Release verification and limitations

FinSight is an **early 0.1 implementation**, not a claim that every target story or production acceptance criterion has passed. `specification.md` describes the intended product. This document records actual verification and must be updated before release.

## Verified locally

- The private source workbook structure was inspected locally without printing financial values.
- The importer parsed all 13,213 source records; a temporary private database import and identical re-import preserved the record count and returned duplicate detection. The temporary database was removed. No source data was copied into fixtures or Git.
- Independent privacy-check regression tests cover staged files, deleted historical secrets, archive/private paths and deliberately reviewed synthetic screenshot approval.
- Real PostgreSQL concurrent reservation and exclusive job-claim regression tests passed in an isolated local test database.
- Python dependency audit found no known vulnerabilities in the installed dependency set at verification time. This is not a security certification.

## Release gates still under integration

Backend/UI complete test runs, frontend production build and browser tests, full Compose boot and backup/restore smoke, final staged/history inspection and public repository/CI verification are recorded by the integrator before publication.

## Important boundaries

- Single-owner deployment. User-owned models prepare for future isolation, but this is not a reviewed multi-tenant service.
- Imported balances are observed account balances, not complete net worth. Missing accounts, investments, liabilities, opening coverage and same-day observations limit historical interpretation.
- Different currencies remain separate; there is no automatic FX service.
- Inference and model-generated explanations are not proof of causality or professional financial advice.
- Provider charges may differ from estimates. Missing/uncertain usage retains budget reservations and may require manual billing reconciliation.
- A workflow definition is not a passing run; check the actual CI result.

## Deferred work

Remaining feature gaps and enhancements are to be linked to public issues after privacy-reviewed publication. No incomplete target story should be represented as delivered simply because its UI navigation or data model exists.
