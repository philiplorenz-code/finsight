"""Exercise deployed OAuth and MCP using only the isolated synthetic smoke owner.

Requires MCP_ENABLED=true and APP_ENV=development in the local Compose API.
Never sends a request to a registered redirect URL or external model service.
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import secrets
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.getenv("FINSIGHT_SYNTHETIC_SMOKE") != "1":
        raise RuntimeError("Explicit synthetic-only smoke guard required")
    origin = "http://localhost:8080"
    config = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines()
                  if line and not line.startswith("#") and "=" in line)
    bootstrap = config.get("FINSIGHT_BOOTSTRAP_SECRET", "")
    if not bootstrap:
        raise RuntimeError("Isolated smoke configuration required")
    owner = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
    public = build_opener(NoRedirect())
    csrf = ""

    def call(path, *, method="GET", data=None, token=None, form=False, authenticated=False,
             expected=200, extra_headers=None):
        headers = {"Origin": origin, "Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if authenticated and csrf:
            headers["X-CSRF-Token"] = csrf
        if extra_headers:
            headers.update(extra_headers)
        body = None
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
            body = (urlencode(data) if form else json.dumps(data)).encode()
        opener = owner if authenticated else public
        try:
            response = opener.open(Request(origin + path, data=body, headers=headers, method=method), timeout=45)
        except HTTPError as error:
            response = error
        with response:
            if response.status != expected:
                raise RuntimeError(f"MCP smoke HTTP mismatch on {path.split('?')[0]}: {response.status}")
            raw = response.read(262145)
            if len(raw) > 262144:
                raise RuntimeError("MCP smoke response exceeded limit")
            result = json.loads(raw) if raw and "json" in response.headers.get("Content-Type", "") else None
            return result, dict(response.headers)

    password = hashlib.sha256((bootstrap + "synthetic-smoke").encode()).hexdigest()
    auth, _ = call("/api/auth/login", method="POST", authenticated=True,
                   data={"email": "smoke@example.invalid", "password": password})
    csrf = auth["csrf_token"]
    transactions, _ = call("/api/transactions", authenticated=True)
    accounts, _ = call("/api/accounts", authenticated=True)
    assert transactions["total"] == 4
    assert all(item["merchant"] == "Synthetic provider" for item in transactions["items"])
    assert {item["name"] for item in accounts} == {"TEST-CHECKING", "TEST-SAVINGS"}

    metadata, _ = call("/.well-known/oauth-protected-resource/mcp")
    assert metadata["resource"] == origin + "/mcp"
    discovery, _ = call("/.well-known/oauth-authorization-server")
    assert "S256" in discovery["code_challenge_methods_supported"]
    call("/mcp", method="POST", data={"jsonrpc": "2.0", "id": 1, "method": "initialize"}, expected=401)
    redirect = "https://synthetic-mcp-client.example.invalid/callback"
    client, _ = call("/oauth/register", method="POST", expected=201, data={
        "client_name": "Synthetic MCP smoke", "redirect_uris": [redirect],
        "token_endpoint_auth_method": "none", "scope": "finance:read finance:transactions"})
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    query = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": redirect,
             "scope": "finance:read finance:transactions", "state": state, "resource": origin + "/mcp",
             "code_challenge": challenge, "code_challenge_method": "S256"}
    _, headers = call("/oauth/authorize?" + urlencode(query), expected=302)
    location = next(v for k, v in headers.items() if k.lower() == "location")
    ident = parse_qs(urlsplit(location).query)["request_id"][0]
    pending, _ = call("/api/mcp/authorization-requests/" + ident, authenticated=True)
    assert pending["client_id"] == client["client_id"]
    approval, _ = call("/api/mcp/authorization-requests/" + ident + "/decision", method="POST",
                       authenticated=True, data={"decision": "allow", "scopes": ["finance:read"]})
    callback = urlsplit(approval["redirect_url"])
    assert callback.hostname == "synthetic-mcp-client.example.invalid"
    values = parse_qs(callback.query)
    assert values["state"] == [state]
    payload = {"grant_type": "authorization_code", "client_id": client["client_id"],
               "code": values["code"][0], "code_verifier": verifier,
               "redirect_uri": redirect, "resource": origin + "/mcp"}
    tokens, _ = call("/oauth/token", method="POST", form=True, data=payload)
    assert tokens["scope"] == "finance:read"
    access = tokens["access_token"]
    protocol = {"MCP-Protocol-Version": "2025-03-26"}

    def rpc(method, params=None, ident=2):
        result, _ = call("/mcp", method="POST", token=access, extra_headers=protocol,
                         data={"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        if "error" in result:
            raise RuntimeError("MCP smoke protocol error")
        return result["result"]

    initialized = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                     "clientInfo": {"name": "finsight-synthetic-smoke", "version": "1"}})
    assert "tools" in initialized["capabilities"]
    tools = rpc("tools/list")["tools"]
    assert len(tools) >= 8
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert len(rpc("prompts/list")["prompts"]) >= 4
    assert len(rpc("resources/list")["resources"]) >= 2
    # Choose a zero-argument capability descriptor without relying on label spelling.
    descriptor = next(tool for tool in tools if "capabilit" in tool["name"])
    result = rpc("tools/call", {"name": descriptor["name"], "arguments": {}})
    assert not result.get("isError", False)
    query = {"start": "2025-10-01", "end": "2025-10-31", "currency": "EUR"}
    overview = rpc("tools/call", {"name": "get_overview", "arguments": {"query": query}})
    assert not overview.get("isError", False)
    row = overview["structuredContent"]["items"][0]
    assert Decimal(row["income"]) == Decimal("2000")
    assert Decimal(row["expenses"]) == Decimal("720")
    assert Decimal(row["surplus"]) == Decimal("1280")
    denied = rpc("tools/call", {"name": "search_transactions", "arguments": {"query": query}})
    assert denied["isError"] is True
    assert "mcp/www_authenticate" in denied["_meta"]
    assert rpc("resources/read", {"uri": "finsight://guide/financial-model"})["contents"]
    assert rpc("prompts/get", {"name": "monthly_review", "arguments": {
        "start": "2025-10-01", "end": "2025-10-31", "currency": "EUR"}})["messages"]
    refresh = {"grant_type": "refresh_token", "client_id": client["client_id"],
               "refresh_token": tokens["refresh_token"], "resource": origin + "/mcp"}
    rotated, _ = call("/oauth/token", method="POST", form=True, data=refresh)
    assert rotated["refresh_token"] != tokens["refresh_token"]
    connections, _ = call("/api/mcp/connections", authenticated=True)
    grant = next(item for item in connections["connections"]
                 if item["client_name"] == "Synthetic MCP smoke" and not item["revoked"])
    call("/api/mcp/connections/" + grant["id"], method="DELETE", authenticated=True)
    for token in (access, rotated["access_token"]):
        call("/mcp", method="POST", token=token,
             data={"jsonrpc": "2.0", "id": 99, "method": "tools/list"}, expected=401)
    call("/oauth/token", method="POST", form=True, data=refresh, expected=400)
    call("/oauth/token", method="POST", form=True, data=payload, expected=400)
    print("Synthetic MCP checks passed: OAuth discovery, PKCE consent, scopes, protocol, prompts, resources, refresh rotation and revocation.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never reflect OAuth state, authorization codes, bearer credentials or bodies.
        raise SystemExit("Synthetic MCP smoke failed; use isolated protocol tests for diagnosis.") from None
