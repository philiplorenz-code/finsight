# Contributing to FinSight

Thank you for helping make self-hosted finance clearer.

1. Read `docs/specification.md`, `docs/stories.md` and `docs/release-status.md`.
2. Open an issue describing a bug or proposed behavior. Never upload actual financial data.
3. Use synthetic fixtures with fictional accounts and references. Do not copy your export into tests.
4. Keep financial arithmetic in deterministic backend services using Decimal/NUMERIC; APIs serialize monetary values as strings.
5. Add regression tests, maintain English docs and DE/EN UI strings, then run backend tests, frontend tests/build and security scans.
6. Submit a focused PR with acceptance criteria and security/privacy implications.

Contributions are licensed under Apache-2.0. By submitting code you confirm you have the right to contribute it. No CLA is currently required. Maintainers should preserve original source evidence and reversible corrections, avoid introducing hidden telemetry and enforce server-side user isolation.
