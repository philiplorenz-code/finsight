# Remote MCP authorization

MCP is disabled by default. Set `MCP_ENABLED=true` and `APP_URL=https://your-finsight.example`
to enable it. `APP_URL` must be an origin, not a path, and is the trusted issuer;
request Host and forwarded headers cannot change it. Plain HTTP is accepted only for
loopback `APP_URL` with `APP_ENV=development` or `APP_ENV=test`. HTTPS is required remotely.
Run Alembic through revision `0002_mcp_oauth` before enabling. Route `/mcp`, `/oauth/*`,
and `/.well-known/*` to the API at the reverse proxy, not the SPA fallback.

## Protocol

* Resource: exactly `APP_URL/mcp` (no trailing slash).
* Resource discovery: `/.well-known/oauth-protected-resource/mcp`.
* Authorization server discovery: `/.well-known/oauth-authorization-server`.
* Public client registration: JSON `POST /oauth/register`, with `redirect_uris`,
  optional `client_name`, `scope`, `grant_types`, `response_types`, and
  `token_endpoint_auth_method: "none"`. No client secrets or remote metadata fetching.
  Standard informational `client_uri`, `logo_uri`, `policy_uri`, `tos_uri` (HTTPS only),
  `contacts` (up to eight email addresses), `software_id` (128 characters), and
  `software_version` (64 characters) are validated but ignored: not fetched, stored,
  returned, rendered, or treated as evidence of client identity.
  Unknown registration metadata is ignored as required by RFC 7591, never fetched,
  persisted or echoed. Parser limits still apply: 16 KiB, 20 fields per object,
  eight nesting levels, 64 entries per array and 256 total value nodes.
  Registration accepts 1–8 exact HTTPS redirects or HTTP loopback redirects, not
  wildcards, fragments, credentials, or redirect patterns. Registered query strings
  cannot predefine OAuth response fields (`code`, `error`, `state`, `iss`). It grants no access.
* `GET /oauth/authorize` requires `response_type=code`, registered `client_id` and
  exact `redirect_uri`, `code_challenge_method=S256`, `code_challenge`, and `resource`.
  `state` is carried back unchanged. Default scope is `finance:read`.
* Authorization redirects to the normal UI at `/mcp/authorize?request_id=<UUID>`.
  The owner signs in normally, reviews client identity, redirect, requested scopes,
  and the explicit disclosure that data leaves the local server. Client names are
  unverified display text, never a trust signal. Never auto-approve a registered client.
* Owner-cookie `GET /api/mcp/authorization-requests/{id}` returns the consent view.
  `POST /api/mcp/authorization-requests/{id}/decision` requires the owner cookie,
  `X-CSRF-Token`, and JSON `{"decision":"allow","scopes":["finance:read"]}` or
  `{"decision":"deny"}`. An explicit nonempty subset is required for approval.
  The response is `{"redirect_url":"..."}`; the UI navigates to it only following
  that explicit decision. Missing/expired/already-decided requests cannot be reused.
* `POST /oauth/token` accepts URL-encoded form fields (or JSON). Public clients use
  `client_id`, not HTTP Basic or client secrets. Code exchange requires
  `grant_type=authorization_code`, `code`, exact `redirect_uri`, `code_verifier`,
  and `resource`. Refresh requires `grant_type=refresh_token`, `refresh_token`,
  `client_id`, and `resource`; optional `scope` can only narrow the previous token.

Scopes: `finance:read` authorizes aggregate views; `finance:transactions` is optional
additional permission for individual transaction detail. The MCP tool layer must
enforce scope on every call. Tokens are opaque, audience-bound, stored only as SHA-256
hashes. Codes expire after two minutes, access tokens after ten minutes, and grants /
rotating refresh tokens after thirty days (fixed maximum, not sliding).
Refresh-token replay with the correctly bound client and resource atomically revokes
the whole grant and marks every family token unusable, including tokens issued by a
previous rotation. Wrong-client or wrong-resource attempts cannot revoke that grant.
Replaying a consumed authorization code also revokes its entire grant/token family,
but only after validating client, resource, exact redirect and PKCE verifier. A
concurrent double redemption therefore yields at most one successful response and
leaves that response's tokens revoked. Clients must not retry consumed credentials;
after replay detection a new explicit owner consent is required.
Revoking an existing grant does not
revoke separately approved grants for the same client.

## Connections and integration contract

Owner-cookie `GET /api/mcp/connections` returns an envelope containing `enabled`,
`endpoint`, supported `scopes`, and `connections` (up to 200 newest grants). Each
connection includes `id`, `client_id`, `client_name`, `scopes`, `resource`, `created_at`,
`expires_at`, and the boolean `revoked`. `endpoint` is the validated resource URL or
`null` when `APP_URL` is invalid. `DELETE /api/mcp/connections/{id}` requires CSRF and
immediately revokes its tokens. Both management endpoints remain available to the
authenticated owner when MCP is disabled or the issuer configuration is invalid.
Consent and public OAuth endpoints remain unavailable while MCP is disabled.
There are no personal access tokens or auto-approval.
Consent details, decisions, and connection management responses set `Cache-Control:
no-store` and `Pragma: no-cache` at the route level.

`app.mcp_auth.router` has absolute root/API paths: mount without a global cookie-CSRF
dependency. Consent/revocation enforce CSRF themselves. Importing the module registers
its models with `Base`; production uses the frozen Alembic migration, not `create_all`.
The MCP transport calls `verify_bearer(token, resource=None)` on every request. It
returns frozen `MCPPrincipal(owner_id, scopes, grant_id)` and opens `SessionLocal`.
`verify_bearer_in_session(db, token)` is the equivalent test seam. Do not cache a
principal across requests or stream resumptions; revocation must be checked anew.
Never accept cookie authentication as a substitute on the remote MCP transport.

Public endpoints and bearer verification return unavailable while disabled.
Per-IP endpoint limits are persisted with hashed keys (10 registrations, 60 authorize
requests, 120 token requests per 15 minutes). By default the actual socket peer is
used and **no forwarding headers are trusted**. `X-Forwarded-For` is always ignored.
To separate clients behind your own reverse proxy, explicitly set
`MCP_TRUSTED_PROXY_CIDRS` to a comma-separated allowlist of proxy IP networks, for
example `172.30.0.2/32,2001:db8:1::2/128` (replace with your actual proxy addresses).
Use a dedicated Docker network with a stable proxy address and trust its `/32` or
`/128` where possible, not an entire shared container subnet. The setting defaults
to empty. An invalid entry disables all forwarded identity trust conservatively.

Only when the actual socket peer belongs to that allowlist does the API accept
exactly one `X-FinSight-Client-IP` header containing a single valid IPv4/IPv6 address.
Missing, duplicate, malformed or comma-list values fall back to the socket peer.
Configure the trusted proxy to **overwrite**, never append or relay, that header:
`proxy_set_header X-FinSight-Client-IP $remote_addr;`. Run Uvicorn with
`--no-proxy-headers` so `request.client.host` remains the actual socket peer. Do not
expose the API directly through an untrusted host that falls within the allowlist.
This header is a privileged identity assertion, not client-provided information.

Without explicit trust, requests behind a proxy conservatively share its bucket.
Even with trust, users behind the same NAT share a bucket; CDN/upstream proxy
addresses also remain shared unless your perimeter safely resolves the real client.
Never enable broad header trust to compensate for an unknown network topology.
Token requests currently share the per-client-IP limit whether credentials are valid
or invalid; perimeter controls are recommended to reduce same-NAT noisy-neighbor DoS.
OAuth bodies are capped at 16 KiB, fields bounded, and errors do not echo credentials.
Configure proxy/ASGI access logs to omit query strings and request/response bodies:
authorize requests contain state and PKCE material. Do not log Authorization headers.
Apply perimeter limits as well; per-IP limits alone do not prevent distributed abuse.

This implements the discovery, public DCR, resource binding and PKCE flow expected by
ChatGPT-compatible remote MCP clients. No live ChatGPT connection test is claimed;
actual compatibility also depends on the deployed MCP SDK transport, HTTPS routing,
the consent UI and the client's current connector support. Test with synthetic data
before authorizing access to real financial information.

The [OpenAI Apps SDK authentication guide](https://developers.openai.com/apps-sdk/build/auth)
was reviewed for this integration. It continues to support DCR with public-client
`none` authentication and S256 PKCE; CIMD, private-key JWT and OIDC identity scopes are
not implemented or advertised here. Issuer identification is advertised because both
allow and deny callbacks include the exact discovery `iss`. Copy the exact callback
shown by the client's connector management UI; do not hard-code a ChatGPT callback
or assume the same callback is used for every connection.
