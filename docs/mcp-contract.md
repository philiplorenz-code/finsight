# MCP integration contract

FinSight MCP is opt-in (`MCP_ENABLED=false`), remote Streamable HTTP at the exact public `${APP_URL}/mcp` URL. `APP_URL` must be the canonical public origin: HTTPS except explicit loopback development. The external client receives requested data only after owner authorization; its model costs are not governed by the internal AI budget.

## Shared interfaces

`app.mcp_auth` exports a root FastAPI `router` (absolute paths, **no** global cookie-CSRF dependency; authenticated decision/revocation handlers apply `current_user` and `require_csrf` themselves), and `verify_bearer(token: str, resource: str | None = None) -> MCPPrincipal`. The immutable principal has `owner_id: str`, `scopes: frozenset[str]`, `grant_id: str`. Verification checks enablement, expiry, hashed credentials, audience and revocation on every request. Invalid credentials raise a safe HTTP error. MCP session cookies do not authorize external tool access.

Scopes: `finance:read` (bounded aggregate analyses, accounts, planning, contracts and import coverage); optional `finance:transactions` (bounded transaction-level merchant/date/category/amount evidence). Neither permits mutations, source JSON, raw reference fields or IBAN disclosure. Empty/minimal grants never imply transaction scope.

## Consent UI APIs

- `GET /api/mcp/authorization-requests/{id}` → `{id,client_id,client_name,redirect_uri,scopes:[str],expires_at,resource,disclosure}`; authenticated, never returns PKCE verifier or raw tokens.
- `POST /api/mcp/authorization-requests/{id}/decision` body `{decision:"allow"|"deny",scopes?:[str]}` → `{redirect_url:str}`; session + CSRF, one-time approval/denial. Allow requires an explicit nonempty subset of requested scopes; deny needs none. Return URI must be exact registered redirect, with OAuth code/error/state added safely. State is opaque and never logged.
- `GET /api/mcp/connections` → `{enabled:bool, endpoint:str|null, scopes:[str], connections:[{id,client_id,client_name,scopes,resource,created_at,expires_at,last_used_at:null,revoked:bool}]}`; `last_used_at` is explicitly unavailable in this version.
- `DELETE /api/mcp/connections/{id}` → `{ok:true}`; owner-scoped session + CSRF; revokes access and refresh tokens for that grant immediately. Management remains available while the operator disables MCP so the owner can still revoke existing grants.

## Public OAuth paths

`/.well-known/oauth-protected-resource/mcp`, `/.well-known/oauth-authorization-server`, `/oauth/register`, `/oauth/authorize`, `/oauth/token`. Public registration never authorizes financial access. Enforce registered exact redirect URIs, PKCE S256, single-use short-lived authorization codes, resource/audience binding, bounded lifetimes and refresh-token rotation. No automatic client URL fetching or plaintext token persistence. Errors and rate limits must not log request bodies, credentials or state.

## Protocol features

Official MCP SDK, stateless Streamable HTTP, typed tool schemas, output bounds and protocol-native resources/prompts. MCP prompts are the portable "skills" mechanism, not a fabricated nonstandard `skills/*` RPC method. Clients vary in prompt/resource support; tools must remain independently useful. Imported strings are untrusted data, not instructions. Query/view evidence may be resolved only through the authorized owner-scoped services.

## Ownership

OAuth work owns its models, tests and migration `0002_mcp_oauth.py`; MCP SDK work owns main-app lifecycle/mounts, tool implementation and dependency declaration; UI work owns consent/settings; the integrator owns proxy, environment, dependency lock, CI and publication checks. Each delivery is validated rather than inferred from this contract.
