# Independent MCP security review

Reviewed 2026-11-14 against the files present during active implementation. No live ChatGPT connection was tested. No real XLSX, `.env`, application database, or user financial records were read. Implementation files were not edited.

**Integrator follow-up:** the contract prose now matches `{ok:true}` and the actual nullable endpoint/connection envelope. Subsequent combined verification passed **377 tests and 66 subtests**, including this review's private PostgreSQL regressions. Through the running non-root Compose/nginx deployment, synthetic OAuth discovery/PKCE/scopes/tool calls/resources/prompts/rotation/revocation and actual browser consent/UI revocation passed. Backup/restore on the migrated schema passed. Those are local HTTP ingress tests, not public TLS or live ChatGPT verification; the shared-proxy deployment caveat remains.

## Final revalidation outcome

**R1–R6 are resolved or mitigated as specified below. No remaining critical/high issue or authorization bypass was established.** All former expected failures were converted into ordinary regressions without relaxing their behavioral acceptance criteria.

Latest independent run: **28 passed, no skips, no xfails**, including SQLite and a newly initialized private PostgreSQL 17.12 cluster. Combined focused run: **159 passed** across the independent review and `test_mcp_auth.py`, `test_mcp_server.py`, `test_mcp_tools.py`, `test_mcp_views.py`.

```sh
FINSIGHT_DATABASE_URL=sqlite:// DATABASE_URL=sqlite:// \
.venv/bin/python -m pytest -q tests/security/test_mcp_review.py \
  apps/api/tests/test_mcp_auth.py apps/api/tests/test_mcp_server.py \
  apps/api/tests/test_mcp_tools.py apps/api/tests/test_mcp_views.py
```

`FINSIGHT_TEST_TMPDIR` is optional; use a short socket-directory path on macOS. The independent fixture retains the short `mcr-` prefix and never uses an application database or an externally supplied PostgreSQL URL. Root integration tests may separately use `FINSIGHT_TEST_POSTGRES_URL`; their reported earlier run is not substituted for the private-cluster results above.

| Finding | Final disposition and evidence |
| --- | --- |
| R1 consent identity/destination | **Resolved.** UI renders callback URI, independently derived callback origin and resource as inert text, warns explicitly that the name is self-asserted/unverified, and includes origin verification in the unchecked consent checkbox. Missing/invalid callbacks block approval. Independent source-contract assertions pass; bilingual spoofed-name browser tests are present in `apps/web/e2e/mcp.spec.ts` but were not browser-executed in this revalidation. |
| R2 shared proxy bucket | **Mitigated with explicit operator configuration.** `MCP_TRUSTED_PROXY_CIDRS` defaults empty. Only an allowlisted actual socket peer may supply exactly one valid `X-FinSight-Client-IP`; untrusted peers, malformed configuration, duplicate/invalid claims and forwarded-for spoofing fail closed. nginx overwrites the custom header with `$remote_addr`; the API container disables Uvicorn proxy-header rewriting. Independent full token-limit tests demonstrate attacker exhaustion does not block another forwarded client when trust is configured, on both databases. Default shared-peer/NAT behavior remains explicitly documented and tested. |
| R3 OAuth tool metadata/step-up | **Resolved.** Actual SDK tool definitions expose exact OAuth scopes in top-level `securitySchemes` and mirrored `_meta`. Independent SDK calls produce native `mcp/www_authenticate` challenges with resource metadata, required scope, error and error description for both read-to-detail and detail-to-read step-up. Focused protocol tests also pass. |
| R4 transaction-only grant | **Resolved.** A real synthetic transaction-only authorization/code exchange passes bearer verification and transport, successfully calls the transaction tool against an empty owner-scoped database, but cannot call aggregate tools without a native read-scope challenge. Principal context is reset after transport completion. Both databases pass. |
| R5 code replay | **Resolved.** Bound replay revokes access and refresh tokens. Wrong client, redirect, verifier or resource cannot revoke the valid grant. Concurrent redemption still has one 200 and one 400, exactly one token pair, and the replay invalidates that pair. This is intentional fail-closed behavior: the winner's returned token is no longer usable after the detected duplicate. Both databases pass. |
| R6 DCR extensions | **Resolved.** Optional standard fields and bounded unknown metadata are accepted without trusting/persisting them. Parser body, node, nesting and field bounds remain enforced; no metadata fetching was added. Original acceptance tests now pass normally. |

### Remaining true issues and operational limits

- **Low/documentation drift:** `docs/mcp-contract.md` still documents DELETE as `{revoked:true}` and older connection fields. Actual working contracts remain `{ok:true}` and the connections envelope with `revoked`. Reproduce by comparing its API list with `mcp_auth.revoke`/`connections`; acceptance is a prose-only correction, not changing the working APIs. No implementation edit was made by this reviewer.
- **Availability limitation, not a newly bypassable trust boundary:** by default, traffic behind one proxy shares its rate bucket; even correctly configured proxy trust cannot distinguish people behind the same public NAT/CDN egress. An unauthenticated caller sharing that identity can still exhaust the allowance. Independent tests preserve this fact rather than pretending the configuration eliminates it. Operators must configure exact trusted proxy networks and perimeter controls as described in `docs/mcp-auth.md`; never use broad public-network trust or rely on arbitrary client forwarding headers. Multi-hop ingress must supply a safely established real client identity.
- **Validation limits:** no live ChatGPT connection, deployed TLS/nginx traffic test, or browser execution was performed by this reviewer. nginx header/path changes and `--no-proxy-headers` were inspected; focused SDK tests exercised exact `/mcp` without a slash redirect, production Host/Origin rejection, native protocol calls and transaction-only access. These do not establish real hosted-client compatibility.
- Imported labels remain untrusted data and external models can still mishandle them. Explicit schemas, output bounds, omitted raw source fields, anonymous defaults and warning metadata reduce exposure; they do not prove resistance of an external model to every prompt injection. Revocation cannot delete data already returned or retract an already executing call.

**Current acceptance:** the tracked implementation findings have passing regressions. Before releasing publicly, verify the actual trusted-proxy/ingress/TLS configuration with synthetic traffic, correct the stale contract prose, and perform any desired real-client linking test without claiming it has already occurred.

---

## Initial review snapshot (historical)

The rest of this report preserves the original findings, reproduction and acceptance criteria for auditability. Its old test totals, open-status language and release checklist describe the initial implementation, **not** the final disposition above.

### Initial outcome

**No critical/high-severity authorization bypass was established.** Synthetic OAuth and owner isolation checks passed on SQLite and a private PostgreSQL 17.12 cluster. Remaining medium issues concern misleading consent, shared-proxy denial of service, and SDK scope/linking compatibility. Do not interpret this review as production certification: deployment and SDK integration were still changing.

Command, from repository root:

```sh
FINSIGHT_DATABASE_URL=sqlite:// DATABASE_URL=sqlite:// .venv/bin/python -m pytest -q tests/security/test_mcp_review.py apps/api/tests/test_mcp_auth.py
```

Latest result: **96 passed, 6 xfailed**. The independent file contributes 10 passes and 6 expected acceptance failures; expected failures are tracked gaps, not evidence that acceptance was met. PostgreSQL tests use independent connections and an isolated, socket-only temporary cluster, never the configured application database. PostgreSQL tests skip when local cluster binaries are unavailable or the process is root. Temporary cluster files are synthetic; the fixture stops its server.

## Initial findings (historical; final dispositions above)

### R1 — Medium: consent hides the destination behind an unverified client name

**Locations:** `apps/web/src/pages/mcp-authorize.tsx` (consent rendering), `apps/web/src/lib/mcp.ts` (`McpAuthorization`), `apps/api/app/mcp_auth.py` (`register`, `authorization_request`).

**Risk/exploit:** Public registration accepts `client_name: "ChatGPT"` and `redirect_uris: ["https://attacker.example/callback"]`. The owner sees that name and an opaque client ID, but neither the registered callback nor the resource and no explicit warning that the name is self-asserted. If deceived into explicit consent, the attacker receives a valid code and can exchange it using its own PKCE verifier. This is a consent-phishing weakness, **not** an automatic OAuth/CSRF bypass; owner interaction remains necessary. Documentation currently claims the owner reviews the redirect.

**Reproduce:** Register those values, start a valid authorization request, visit `/mcp/authorize?request_id=...`; observe that the attacker's callback hostname is absent. `test_consent_displays_unverified_client_destination` tracks the missing rendering via source assertions; this is not a browser execution test.

**Acceptance:** Render callback URI/origin and resource as inert text, clearly label the client name as unverified, include `redirect_uri` in the frontend type, and add a rendered/browser test with a spoofed trusted name. Never fetch client logos or treat registered display metadata as identity proof.

### R2 — Medium, deployment-dependent: unauthenticated traffic can exhaust a shared OAuth proxy bucket

**Locations:** `apps/api/app/mcp_auth.py::rate_limit`; `apps/web/nginx.conf` exact `/mcp`, `/mcp/`, `/oauth/`, `/.well-known/` proxy blocks.

**Risk/exploit:** Limits use `request.client.host` before parsing/authenticating requests. The OAuth nginx blocks do not overwrite/set a real-client forwarding header. With ordinary proxy deployment, multiple clients therefore share nginx's source-IP bucket. An unauthenticated attacker can submit 120 invalid `/oauth/token` requests and deny a legitimate code exchange/refresh for the remainder of the 15-minute window. Similar interference needs only 10 registrations or 60 authorization requests. Existing short-lived tokens continue to work until expiry. This is availability loss, not token theft.

**Reproduce:** `test_shared_proxy_bucket_allows_unauthenticated_token_endpoint_dos` simulates distinct authenticated/unauthenticated clients sharing one ASGI peer address on both databases; the legitimate exchange returns 429. Proxy behavior is established by configuration inspection, not a running nginx test.

**Acceptance:** Configure and test a trusted forwarding boundary: nginx must overwrite the relevant client-IP header; ASGI must trust only the intended proxy, never arbitrary public forwarding headers. Add perimeter abuse controls and consider separating authenticated valid-client token traffic from unauthenticated failures. Document any remaining NAT/shared-egress limitations. Do not simply trust incoming X-Forwarded-For globally.

### R3 — Medium interoperability: tool OAuth declarations and step-up challenges missing

**Locations:** `apps/api/app/mcp_server.py::create_server`, `SafeMCP.call_tool`, `BearerMiddleware`.

**Risk:** Newly arrived SDK tools have read-only annotations but no per-tool OAuth `securitySchemes`. Scope errors become generic tool errors without `_meta["mcp/www_authenticate"]`. A `finance:read` connection attempting transaction tools cannot reliably trigger ChatGPT's documented step-up linking UI. HTTP 401 discovery is present, but is not a replacement for the documented tool-level contract. No successful real-client linking is claimed.

**Reproduce:** `test_sdk_tools_advertise_oauth_scopes` obtains actual SDK tool definitions and finds no OAuth declarations. With a read-only principal, invoking transaction tools reaches the permission error converted by `SafeMCP.call_tool` into an unstructured generic rejection.

**Acceptance:** Advertise `oauth2` plus actual required scopes per tool; return a safe native auth error with `_meta["mcp/www_authenticate"]` including resource metadata, `error`, `error_description`, and required scope when permission is missing. Test SDK `tools/list` and `tools/call` responses, both unauthenticated discovery and authenticated step-up. Keep actual server-side scope checks regardless of metadata.

### R4 — Medium correctness: scopes accepted by consent can be unusable at the transport

**Locations:** `apps/api/app/mcp_auth.py::decision`, `apps/web/src/pages/mcp-authorize.tsx`, `apps/api/app/mcp_server.py::BearerMiddleware`.

**Risk/reproduction:** Request and approve only `finance:transactions`, which is a supported nonempty subset and is accepted by consent. The token verifies successfully, but middleware rejects all MCP requests because it requires `finance:read` globally. This is a broken permission contract, not excess access. Static control-flow inspection establishes the inconsistency; no end-to-end SDK test was added for it.

**Acceptance:** Choose one consistent policy: transaction scope requires explicitly consented read scope (enforce in authorization/consent/UI and document the dependency), or transport allows supported grants and each method/tool enforces its own required scopes. Test read-only, transaction-only, both, and narrowed refresh scopes end-to-end.

### R5 — Low defense-in-depth: code replay rejects the replay but leaves issued tokens active

**Location:** `apps/api/app/mcp_auth.py::token` authorization-code branch.

**Risk/reproduction:** Redeem a code, submit the identical bound code/client/redirect/verifier/resource request again, then verify the first access token: replay returns `invalid_grant` but the token still works. `test_code_replay_revokes_issued_tokens` reproduces this on SQLite and PostgreSQL. Code consumption itself is atomic and single-use; this does **not** bypass PKCE or issue a second token pair.

**Acceptance:** Consider following RFC 6749 §4.1.2's **SHOULD** to revoke tokens previously issued for a reused code. Only revoke after validating client/resource/redirect/PKCE binding, to avoid turning a leaked code alone into a revocation oracle. Alternatively document an explicit risk decision for this recommendation. Preserve single-winner race behavior.

### R6 — Low standards compatibility: unknown DCR metadata still causes rejection

**Location:** `apps/api/app/mcp_auth.py::register` metadata allowlist.

**Risk/reproduction:** After the bounded standard-metadata fix, `client_uri`, `logo_uri`, contacts and software fields work. Adding an innocuous unknown field such as `review_extension: "ignored"` still returns `invalid_client_metadata`. RFC 7591 §3.2.1 says the authorization server MUST ignore unrecognized metadata. The independent DCR acceptance test reproduces the remaining rejection. This may break future client extensions; it is **not** evidence that today's actual ChatGPT DCR payload fails.

**Acceptance:** Within existing body/field bounds, ignore unrecognized registration metadata without fetching, persisting, echoing, or trusting it. Continue strict validation of security-relevant recognized fields. If deliberately retaining a narrower profile, document the standards deviation rather than claiming full RFC 7591 behavior.

## Resolved / validated during review

- **Refresh replay:** correctly bound replay revokes the whole family; fresh lookup after PostgreSQL grant locking avoids stale identity-map state. Independent concurrent refresh tests pass on both databases, and both old/new access tokens and the winning rotated refresh are unusable afterward. Wrong-client requests do not constitute authority to revoke a victim grant.
- **Code concurrency:** simultaneous independent-connection redemptions produce exactly one 200 and one 400, with only one access/refresh pair, on both databases. Grant row locking plus conditional code update protects PostgreSQL as well as SQLite.
- **Standard DCR metadata:** bounded common informational fields are now accepted without URL fetching. This resolves the initial standard-field rejection, separate from R6.
- **No-store:** explicit sensitive authorization API response headers were added during review. Independent connections and token response checks pass. Main middleware also sets no-store globally; deployment does not need to rely solely on that for the newly decorated routes.
- **Issuer identification:** metadata now advertises `authorization_response_iss_parameter_supported: true`; successful and denied callback construction includes the configured `iss`. Host headers cannot change the issuer. No CIMD support is advertised.
- **Owner/scope isolation:** synthetic foreign-account queries return no rows, caller-supplied `owner_id` is rejected by strict query models, transaction tools/name opt-in reject `finance:read`-only callers. SQL predicates bind transactions and accounts to the verified owner. No arbitrary SQL/URL/filesystem arguments or outbound fetching were observed in these modules.
- **Other OAuth checks:** existing auth tests pass for default-off, exact redirect/query preservation, S256 PKCE, resource/client binding, one-time consent, session authentication and CSRF, expiration, hashed credential storage, revocation while disabled, narrowing and replay, bounded generic errors. Opaque grant/resource binding is sufficient here; JWT signatures/JWKS are not required for opaque server-issued tokens.

## Protocol, deployment and data handling observations

- nginx routes **exact** `/mcp` and `/mcp/` to API; `/mcp/authorize` reaches the SPA fallback. `/oauth/` and `/.well-known/` are API prefixes. No broad `/mcp/` prefix was found that would swallow consent. Streaming buffering/cache are off for MCP. Syntax/live ingress/TLS deployment was not tested; the integrator owns these checks.
- nginx access logging is off, high-noise error logging is suppressed, and `infrastructure/docker/api.Dockerfile` starts uvicorn with `--no-access-log`. This avoids the identified query-string logging concern in the supplied container command. Operators must preserve this at any outer ingress and avoid body/Authorization logging.
- No wildcard credentialed CORS policy was observed. New SDK transport settings validate configured Origin/Host and enable DNS-rebinding protection. Do not broaden them solely to work around a client issue. Production allowances for localhost/testserver should be narrowed if not needed. Browser-facing CORS/preflight behavior and deployed TLS remain integration checks, not demonstrated exploits.
- SDK middleware accepts one bearer header, not cookies, revalidates each HTTP request, sets/reset principal context, and uses stateless transport. No long-lived authenticated session cache was observed. Active calls already executing at revocation cannot retract previously read data; revocation must block subsequent requests.
- `mcp_tools.py` bounds dates/pages/results, uses explicit output models, omits raw descriptions/source JSON/IBAN fields and anonymizes names by default. Imported categories/labels/merchants remain untrusted text with explicit warnings; they are not executed. That reduces prompt-injection opportunity, but cannot guarantee an external model ignores adversarial imported strings. Client-side instructions are not security boundaries.
- Migration 0002 is frozen, has required indexed foreign keys and timezone-aware expiry columns, and excludes the existing users table from upgrade/downgrade creation/deletion. Existing migration model/schema tests passed. Actual Alembic upgrade/downgrade against PostgreSQL was not exercised by this independent review.
- `docs/mcp-contract.md` still describes DELETE as `{revoked:true}` and some connection fields differently from the current working `{ok:true}` / `revoked` / envelope API. This is documentation drift, not a security issue; do not change good working API envelopes just to match stale prose.

## Current OpenAI authentication documentation

Fetched directly during this review: <https://developers.openai.com/apps-sdk/build/auth>.

- **Remote public DCR remains supported.** CIMD is preferred when implemented/selected, but is not a mandatory addition to this DCR-only server. Advertising registration plus `token_endpoint_auth_methods_supported: ["none"]` and S256 is compatible with the documented public-client option. Do not add remote metadata fetching just for parity; doing so introduces SSRF policy work.
- `resource` is expected at authorization and token endpoints; this implementation checks the exact canonical `/mcp` resource and binds the opaque grant to it.
- Custom finance scopes are valid; the server does not advertise OIDC scopes, so adding `openid`, `email`, or `profile` is not required. Workspace-domain identity restrictions would need a separate, deliberately implemented OIDC/UserInfo capability.
- Current guidance distinguishes callback-ID-specific and stable callback URLs. Since issuer identification is now advertised, copy the exact redirect shown for the actual connector and validate returned `iss`; do not hard-code legacy callback assumptions or auto-trust arbitrary clients named ChatGPT.
- The guide explicitly requires per-tool auth metadata and native auth errors for tool-level linking (R3). Profile tooling and optional mTLS are additional capabilities, not substitutes for owner OAuth authorization.

**Release acceptance:** fix or explicitly accept R1–R4, retain reproducible auth/owner-isolation tests, run deployed SDK initialization/tools/resources/prompts and auth-step-up tests, validate nginx/TLS/trusted-proxy behavior with synthetic data, and only then attempt a real client connection. No live-client result is implied by this report.
