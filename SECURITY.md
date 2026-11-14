# Security policy

FinSight is early-stage software handling sensitive information. A passing test suite is not an independent security audit. Do not expose the initial release directly to the public Internet.

## Reporting

**Do not publish vulnerabilities, credentials, spreadsheets or financial details in a public issue.** Use the repository's GitHub **Security → Report a vulnerability** private reporting feature if enabled. If unavailable, request a private contact channel in an issue without disclosing technical details, or contact the repository owner through their GitHub profile. Never use a public issue as a secret-delivery channel.

Include affected version, synthetic reproduction, impact and suggested mitigation. Maintainers will coordinate disclosure and fixes when possible; no response SLA is promised.

## Supported versions

Only the latest released version is maintained. During initial development, deployments should track reviewed fixes and keep encrypted recoverable backups. Dependency automation and CI audits do not replace patch review or runtime hardening.
