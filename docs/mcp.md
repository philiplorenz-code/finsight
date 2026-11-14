# FinSight remote MCP

FinSight uses the **official Python `mcp` SDK**, version `>=1.26,<2`, with stateless StreamableHTTP and JSON responses. This is a standard MCP server, not a custom REST tool adapter. It exposes read-only tools, trusted static resources and protocol-native prompts. No model/provider request is made by the MCP server.

## Enable and connect

MCP is **off by default**. Set `MCP_ENABLED=true` and a canonical public HTTPS `APP_URL`, apply the OAuth migration and restart the API. HTTP issuers are allowed only for loopback development/test with the corresponding `APP_ENV`. Never use a real financial export for a smoke test.

Configure your MCP client with **`APP_URL/mcp`**, not `/api/mcp`. Both `/mcp` and `/mcp/` serve the transport directly, without a slash redirect. OAuth resources/tokens always bind to the canonical URL **without the trailing slash**.

Discovery:

- `APP_URL/.well-known/oauth-protected-resource/mcp`
- `APP_URL/.well-known/oauth-authorization-server`

OAuth public-client registration, authorization and token exchange live under `/oauth/`. Owner consent and connection management live under `/api/mcp/`; the browser consent page is `/mcp/authorize`. Root discovery/OAuth routes must not inherit the browser API's blanket CSRF dependency. Cookie-authenticated decisions and revocation enforce CSRF inside the OAuth module.

Use the exact callback URL shown by your actual client. An unverified display name such as “ChatGPT” is not evidence of client identity. Review the callback destination, resource and requested scopes before approving. No real ChatGPT connection is asserted by the tests below; client/account eligibility, available connector UI, callback behavior and deployed ingress/TLS remain deployment checks.

## Authorization and privacy

Every transport request—including initialize, tool calls, resource reads and prompt requests—must carry a bearer token. Browser cookies never substitute for a token. The verifier rechecks expiry/revocation and canonical resource binding per request; there is no authenticated MCP session cache. Revocation stops subsequent requests; data already returned cannot be recalled.

Any valid nonempty supported grant can initialize, inspect capabilities/views and read guides/prompts:

| Scope | Permission |
| --- | --- |
| `finance:read` | Aggregate views, anonymous accounts, import freshness, savings plans, obligations and incomplete financial-health indicators |
| `finance:transactions` | Bounded individual transaction evidence and inferred recurring-payment details; opt-in imported names/merchant labels |

These scopes are independent. A transaction-only grant does **not** gain aggregate access. A read-only grant cannot retrieve transaction evidence or enable `include_names`. Tool definitions advertise actual required OAuth scopes both at top-level `securitySchemes` and `_meta.securitySchemes`. Missing tool permissions produce an MCP error result with `_meta["mcp/www_authenticate"]`, including `insufficient_scope`, required scope and the protected-resource metadata URL, to support native step-up consent. Authorization is enforced server-side regardless of this metadata.

All queries bind to the verified owner. Outputs are explicit Pydantic allowlists, not ORM serialization. Account/bucket/obligation names are anonymous by default; merchant labels require both `include_names=true` and transaction permission. Raw descriptions, source JSON, source references, source account keys, import filenames and IBAN fields are never exposed. Imported categories/labels/merchants are marked as **untrusted data**, including output metadata; prompts instruct clients never to execute their embedded instructions. These warnings do not guarantee that an external model resists prompt injection.

This feature deliberately exports approved financial data to the client's environment. The MCP client pays for its model calls; FinSight's external-AI budget and provider-consent policy are not the authorization/billing boundary for MCP. Disable or revoke the connection to stop further MCP export.

## Bounds and operational controls

- Read-only, fixed SQLAlchemy queries; no arbitrary SQL, paths, URLs, network fetches or mutation tools.
- At most 366 inclusive calendar days per query and comparison period; one currency, never implicit FX.
- Default page size 20; maximum 100. One page per call. Exact totals accompany bounded rows unless a documented inference/calculation cap applies.
- Tool results, including structured and compatibility text representations, are capped at 48,000 serialized bytes. Rows may be removed with `has_more=true`; retry using a smaller page size, not an assumed full-page offset.
- Recurrence examines at most 2,000 source rows. Shared allocation backing examines at most 1,000 buckets and 10,000 allocations; capped calculations return explicit unavailable funding values.
- No complete net-worth or safe-to-spend guarantee. Missing coverage and unavailable measures remain explicit.
- The SDK session manager runs only while the enabled API lifespan is active and shuts down with it. Disabled requests return 404 without starting background MCP tasks. Change enablement through environment configuration and restart, not runtime toggling.
- Production DNS-rebinding protection allows **only the exact `APP_URL` authority**, including its configured port. Loopback/test Host allowances are limited to `APP_ENV=development` or `test`. The allowed Origin is the configured `APP_URL`.
- Configure ingress to preserve MCP methods and forward the configured Host, preserve authorization, and avoid logging headers, bodies or sensitive OAuth query strings. Do not add wildcard CORS or trust arbitrary forwarding headers. Deployment owns trusted proxy boundaries and perimeter abuse controls.

`finsight.mcp.audit` emits only allowlisted tool names and returned row counts. There is no existing general audit model, so this implementation creates **no additional audit table**. Configure protected log retention if durable audit is required; do not enable raw SDK/HTTP debug payload logging. Validation/database errors return generic tool errors without exception/source values.

## Local protocol verification

From repository root, with the API dependencies installed:

```sh
FINSIGHT_DATABASE_URL=sqlite:// DATABASE_URL=sqlite:// PYTHONPATH=apps/api \
  .venv/bin/python -m pytest -q apps/api/tests/test_mcp_server.py apps/api/tests/test_mcp_tools.py
```

These tests use synthetic SQLite records and the official SDK `ClientSession`/StreamableHTTP client over `httpx.ASGITransport`: initialization, schemas, annotated tools, structured calls, resources, prompts, anonymous outputs, independent scopes, native step-up, cookie rejection, per-request fake revocation, context isolation, redirect-free canonical/slash URLs (including the actual main app), result caps and exact production Host/Origin validation. OAuth cryptography/binding/rotation and real database concurrency are covered separately by the OAuth/security suites. No external AI/client service, real XLSX, `.env` or production database is needed.

See [tool contract](mcp-tools.md) and [independent security review](mcp-security-review.md).
