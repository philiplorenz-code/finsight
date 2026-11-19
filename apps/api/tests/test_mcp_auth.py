"""Synthetic-only OAuth tests; no network clients or live financial data."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

from app import mcp_auth as oauth
from app.auth import COOKIE, token_hash
from app.db import get_db
from app.models import Session, User

RESOURCE = "https://finance.example/mcp"
REDIRECT = "https://client.example/callback"
VERIFIER = "a" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture
def mcp_client(db, monkeypatch):
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("APP_URL", "https://finance.example")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MCP_TRUSTED_PROXY_CIDRS", raising=False)
    owner = User(email="oauth-owner@example.test", password_hash="unused", owner_slot=1)
    db.add(owner)
    db.flush()
    db.add(Session(id=token_hash("synthetic-session"), user_id=owner.id,
                   csrf_token="synthetic-csrf", expires_at=oauth.now() + timedelta(hours=1)))
    db.commit()
    app = FastAPI()
    app.include_router(oauth.router)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        client.cookies.set(COOKIE, "synthetic-session")
        client.headers["X-CSRF-Token"] = "synthetic-csrf"
        yield client


def register(client, **changes):
    data = {"redirect_uris": [REDIRECT], "client_name": "Synthetic client"}
    data.update(changes)
    return client.post("/oauth/register", json=data)


def authorize(client, client_id=None, **changes):
    if client_id is None:
        client_id = register(client).json()["client_id"]
    data = {"client_id": client_id, "redirect_uri": REDIRECT, "response_type": "code",
            "code_challenge": CHALLENGE, "code_challenge_method": "S256", "resource": RESOURCE,
            "scope": "finance:read finance:transactions", "state": "synthetic-state"}
    data.update(changes)
    return client.get("/oauth/authorize", params=data, follow_redirects=False)


def approve(client, scopes=None):
    registration = register(client).json()
    response = authorize(client, registration["client_id"])
    assert response.status_code == 302
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    view = client.get(f"/api/mcp/authorization-requests/{ident}")
    assert view.status_code == 200
    assert view.headers["cache-control"] == "no-store"
    assert "leaves your local" in view.json()["disclosure"]
    decision = client.post(f"/api/mcp/authorization-requests/{ident}/decision",
                           json={"decision": "allow", "scopes": scopes or ["finance:read"]})
    assert decision.status_code == 200
    assert decision.headers["cache-control"] == "no-store"
    callback = parse_qs(urlsplit(decision.json()["redirect_url"]).query)
    assert callback["state"] == ["synthetic-state"]
    assert callback["iss"] == ["https://finance.example"]
    return registration["client_id"], callback["code"][0], ident


def exchange(client, client_id, code, **changes):
    data = {"grant_type": "authorization_code", "client_id": client_id, "code": code,
            "redirect_uri": REDIRECT, "code_verifier": VERIFIER, "resource": RESOURCE}
    data.update(changes)
    return client.post("/oauth/token", data=data)


def refresh(client, client_id, token, **changes):
    data = {"grant_type": "refresh_token", "client_id": client_id, "refresh_token": token, "resource": RESOURCE}
    data.update(changes)
    return client.post("/oauth/token", data=data)


def test_discovery_and_disabled(mcp_client, monkeypatch):
    metadata = mcp_client.get("/.well-known/oauth-authorization-server").json()
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert metadata["scopes_supported"] == sorted(oauth.SCOPES)
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert mcp_client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == RESOURCE
    monkeypatch.delenv("MCP_ENABLED")
    for path in ["/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp", "/oauth/authorize"]:
        assert mcp_client.get(path).status_code == 404
    assert register(mcp_client).status_code == 404
    assert mcp_client.post("/oauth/token", data={}).status_code == 404
    with pytest.raises(HTTPException) as error:
        oauth.verify_bearer("x" * 64)
    assert error.value.status_code == 404


@pytest.mark.parametrize("origin", ["", "http://remote.example", "https://example.com/path", "https://synthetic-user:synthetic-pass@example.com", "https://example.com/#", "http://localhost:8000", "HTTP://localhost:8000"])
def test_unsafe_issuer_fails_closed(mcp_client, monkeypatch, origin):
    monkeypatch.setenv("APP_URL", origin)
    assert mcp_client.get("/.well-known/oauth-authorization-server").status_code == 503


def test_development_loopback_issuer(mcp_client, monkeypatch):
    monkeypatch.setenv("APP_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("APP_ENV", "development")
    assert mcp_client.get("/.well-known/oauth-authorization-server").json()["issuer"] == "http://127.0.0.1:8000"


@pytest.mark.parametrize("redirect", ["http://client.example/callback", "javascript:alert(1)", "https://client.example/#fragment", "https://synthetic-user:synthetic-pass@client.example", "https://client.example/\r\nheader", "https://*.example/callback", "https://client.example\\@evil.test", "https://client.example/cb#", "https://client.example:invalid/cb", "https://client.example/cb?%63ode=shadow"])
def test_registration_rejects_unsafe_redirect(mcp_client, redirect):
    assert register(mcp_client, redirect_uris=[redirect]).status_code == 400


@pytest.mark.parametrize("redirect", ["http://localhost:1234/callback", "http://127.0.0.1/cb", "http://[::1]:9000/cb", REDIRECT])
def test_registration_accepts_safe_redirect(mcp_client, redirect):
    response = register(mcp_client, redirect_uris=[redirect])
    assert response.status_code == 201
    assert "client_secret" not in response.json()


def test_registration_limits_and_no_fetch(mcp_client):
    assert register(mcp_client, redirect_uris=[]).status_code == 400
    assert register(mcp_client, redirect_uris=[REDIRECT] * 2).status_code == 400
    assert register(mcp_client, client_name="x" * 161).status_code == 400
    assert register(mcp_client, jwks_uri="http://127.0.0.1/private").status_code == 201
    assert register(mcp_client, token_endpoint_auth_method="client_secret_basic").status_code == 400
    assert register(mcp_client, scope="finance:write").status_code == 400


def test_standard_informational_registration_metadata(mcp_client):
    metadata = {"client_uri": "https://chatgpt.com/", "logo_uri": "https://client.example/logo.png",
                "policy_uri": "https://client.example/privacy", "tos_uri": "https://client.example/terms",
                "contacts": ["synthetic-contact@example.test"], "software_id": "synthetic-client",
                "software_version": "1.0.0"}
    result = register(mcp_client, **metadata)
    assert result.status_code == 201
    assert set(result.json()).isdisjoint(metadata)
    response = authorize(mcp_client, result.json()["client_id"])
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    view = mcp_client.get(f"/api/mcp/authorization-requests/{ident}").json()
    assert set(view).isdisjoint(metadata)
    assert "logo.png" not in str(view)


def test_unknown_registration_metadata_ignored_not_echoed_or_stored(mcp_client, db):
    unknown = {"jwks_uri": "http://127.0.0.1/private", "vendor_extension": {"url": "file:///private", "flag": True}}
    response = register(mcp_client, **unknown)
    assert response.status_code == 201
    assert set(response.json()).isdisjoint(unknown)
    client = db.get(oauth.MCPClient, response.json()["client_id"])
    assert set(client.__dict__).isdisjoint(unknown)
    assert client.redirect_uris == [REDIRECT]
    # Unknown fields cannot weaken validation of recognized security fields.
    assert register(mcp_client, redirect_uris=["http://remote.example/cb"], **unknown).status_code == 400
    assert register(mcp_client, token_endpoint_auth_method="client_secret_basic", **unknown).status_code == 400


def test_unknown_registration_metadata_keeps_parser_bounds(mcp_client):
    nested = "value"
    for _ in range(10):
        nested = {"nested": nested}
    assert register(mcp_client, extension=nested).status_code == 400
    assert register(mcp_client, **{f"extension_{i}": i for i in range(20)}).status_code == 400
    assert register(mcp_client, extension=list(range(65))).status_code == 400


@pytest.mark.parametrize("metadata", [
    {"client_uri": "http://127.0.0.1/private"}, {"logo_uri": "javascript:alert(1)"},
    {"policy_uri": "https://synthetic-user:synthetic-secret@client.example/"}, {"tos_uri": "https://*.example/"},
    {"client_uri": "https://client.example/" + "a" * 2048}, {"logo_uri": {}},
    {"contacts": ["synthetic@example.test"] * 9}, {"contacts": ["not an email"]},
    {"contacts": [{}]}, {"contacts": "synthetic@example.test"},
    {"software_id": "a" * 129}, {"software_version": "a" * 65},
    {"software_id": "bad\nvalue"}, {"software_version": {}},
])
def test_informational_registration_metadata_is_bounded_and_safe(mcp_client, metadata):
    assert register(mcp_client, **metadata).status_code == 400


def test_registered_query_preserved_and_exact_redirect(mcp_client):
    redirect = REDIRECT + "?custom=hello%20world&other=%2F"
    client_id = register(mcp_client, redirect_uris=[redirect]).json()["client_id"]
    assert authorize(mcp_client, client_id, redirect_uri=REDIRECT).status_code == 400
    response = authorize(mcp_client, client_id, redirect_uri=redirect)
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    response = mcp_client.post(f"/api/mcp/authorization-requests/{ident}/decision", json={"decision": "deny"})
    assert response.json()["redirect_url"].startswith(redirect + "&error=access_denied")


def test_host_header_cannot_change_issuer(mcp_client):
    result = mcp_client.get("/.well-known/oauth-authorization-server", headers={"Host": "attacker.example"})
    assert result.json()["issuer"] == "https://finance.example"


@pytest.mark.parametrize("changes", [{"redirect_uri": REDIRECT + "/"}, {"resource": "https://evil.example/mcp"},
                                     {"code_challenge_method": "plain"}, {"code_challenge": "short"},
                                     {"response_type": "token"}, {"scope": "finance:write"}])
def test_authorize_binding(mcp_client, changes):
    assert authorize(mcp_client, **changes).status_code == 400


def test_authorize_does_not_autoapprove(mcp_client, db):
    assert authorize(mcp_client).status_code == 302
    assert db.scalar(select(oauth.MCPGrant)) is None
    assert db.scalar(select(oauth.MCPCode)) is None


def test_consent_csrf_and_explicit_scopes(mcp_client):
    response = authorize(mcp_client)
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    path = f"/api/mcp/authorization-requests/{ident}/decision"
    assert mcp_client.post(path, json={"decision": "allow"}).status_code == 400
    assert mcp_client.post(path, json={"decision": "allow", "scopes": ["finance:write"]}).status_code == 400
    assert mcp_client.post(path, json={"decision": "allow", "scopes": ["finance:read"]},
                           headers={"X-CSRF-Token": "synthetic-wrong"}).status_code == 403
    denied = mcp_client.post(path, json={"decision": "deny"})
    assert parse_qs(urlsplit(denied.json()["redirect_url"]).query)["error"] == ["access_denied"]
    assert mcp_client.post(path, json={"decision": "deny"}).status_code == 404


def test_owner_cookie_required(mcp_client):
    response = authorize(mcp_client)
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    mcp_client.cookies.clear()
    assert mcp_client.get(f"/api/mcp/authorization-requests/{ident}").status_code == 401
    assert mcp_client.get("/api/mcp/connections").status_code == 401
    assert mcp_client.post(f"/api/mcp/authorization-requests/{ident}/decision", json={"decision": "deny"}).status_code == 401


def test_full_flow_hashes_and_revocation(mcp_client, db, monkeypatch):
    client_id, code, ident = approve(mcp_client)
    response = exchange(mcp_client, client_id, code)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    tokens = response.json()
    principal = oauth.verify_bearer_in_session(db, tokens["access_token"])
    assert principal.scopes == frozenset({"finance:read"})
    assert db.get(oauth.MCPCode, oauth.digest(code)).used
    assert db.get(oauth.MCPCode, code) is None
    assert {row.id for row in db.scalars(select(oauth.MCPToken))} == {
        oauth.digest(tokens["access_token"]), oauth.digest(tokens["refresh_token"])}
    monkeypatch.setattr(oauth, "SessionLocal", lambda: db)
    assert oauth.verify_bearer(tokens["access_token"], RESOURCE) == principal
    with pytest.raises(HTTPException):
        oauth.verify_bearer(tokens["access_token"], "https://evil.example/mcp")
    assert mcp_client.get(f"/api/mcp/authorization-requests/{ident}").status_code == 404
    connections_response = mcp_client.get("/api/mcp/connections")
    assert connections_response.headers["cache-control"] == "no-store"
    envelope = connections_response.json()
    assert envelope["enabled"] is True
    assert envelope["endpoint"] == RESOURCE
    assert envelope["scopes"] == sorted(oauth.SCOPES)
    connection = envelope["connections"][0]
    assert connection["client_name"] == "Synthetic client"
    assert connection["expires_at"]
    assert connection["revoked"] is False
    assert connection["id"] == principal.grant_id
    assert mcp_client.delete(f"/api/mcp/connections/{principal.grant_id}",
                             headers={"X-CSRF-Token": "synthetic-wrong"}).status_code == 403
    assert mcp_client.delete(f"/api/mcp/connections/{principal.grant_id}").status_code == 200
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["access_token"])
    assert refresh(mcp_client, client_id, tokens["refresh_token"]).status_code == 400


@pytest.mark.parametrize("changes", [{"client_id": "wrong"}, {"redirect_uri": REDIRECT + "/"},
                                     {"code_verifier": "b" * 64}, {"resource": "https://evil.example/mcp"}])
def test_code_exchange_binding_does_not_consume_valid_code(mcp_client, changes):
    client_id, code, _ = approve(mcp_client)
    data = {"grant_type": "authorization_code", "client_id": client_id, "code": code,
            "redirect_uri": REDIRECT, "code_verifier": VERIFIER, "resource": RESOURCE}
    data.update(changes)
    assert mcp_client.post("/oauth/token", data=data).status_code == 400
    assert exchange(mcp_client, client_id, code).status_code == 200


def test_refresh_rotation_narrowing_and_replay(mcp_client, db):
    client_id, code, _ = approve(mcp_client, ["finance:read", "finance:transactions"])
    tokens = exchange(mcp_client, client_id, code).json()
    assert refresh(mcp_client, "wrong", tokens["refresh_token"]).status_code == 400
    narrowed = refresh(mcp_client, client_id, tokens["refresh_token"], scope="finance:read")
    assert narrowed.status_code == 200
    current = narrowed.json()
    assert current["refresh_token"] != tokens["refresh_token"]
    assert current["scope"] == "finance:read"
    assert refresh(mcp_client, client_id, current["refresh_token"], scope="finance:transactions").status_code == 400
    # The revoked-token replay guard must not become a cross-client/resource DoS.
    assert refresh(mcp_client, "wrong-client", tokens["refresh_token"]).status_code == 400
    assert refresh(mcp_client, client_id, tokens["refresh_token"], resource="https://other.example/mcp").status_code == 400
    assert oauth.verify_bearer_in_session(db, tokens["access_token"])
    assert oauth.verify_bearer_in_session(db, current["access_token"]).scopes == frozenset({"finance:read"})
    assert refresh(mcp_client, client_id, tokens["refresh_token"]).status_code == 400
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["access_token"])
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, current["access_token"])
    assert refresh(mcp_client, client_id, current["refresh_token"]).status_code == 400
    assert all(row.used for row in db.scalars(select(oauth.MCPToken)))
    assert mcp_client.get("/api/mcp/connections").json()["connections"][0]["revoked"] is True


def test_bound_code_replay_revokes_original_and_rotated_family(mcp_client, db):
    client_id, code, _ = approve(mcp_client)
    original = exchange(mcp_client, client_id, code).json()
    for changes in [{"client_id": "wrong"}, {"redirect_uri": REDIRECT + "/"},
                    {"resource": "https://other.example/mcp"}, {"code_verifier": "b" * 64}]:
        fields = {"grant_type": "authorization_code", "client_id": client_id, "code": code,
                  "redirect_uri": REDIRECT, "resource": RESOURCE, "code_verifier": VERIFIER}
        fields.update(changes)
        assert mcp_client.post("/oauth/token", data=fields).status_code == 400
        assert oauth.verify_bearer_in_session(db, original["access_token"])
    rotated = refresh(mcp_client, client_id, original["refresh_token"]).json()
    assert oauth.verify_bearer_in_session(db, rotated["access_token"])
    # A retained consumed-code hash still identifies replay after code expiry.
    db.get(oauth.MCPCode, oauth.digest(code)).expires_at = oauth.now() - timedelta(seconds=1)
    db.commit()
    assert exchange(mcp_client, client_id, code).status_code == 400
    for tokens in [original, rotated]:
        with pytest.raises(HTTPException):
            oauth.verify_bearer_in_session(db, tokens["access_token"])
        assert refresh(mcp_client, client_id, tokens["refresh_token"]).status_code == 400
    assert all(row.used for row in db.scalars(select(oauth.MCPToken)))
    assert mcp_client.get("/api/mcp/connections").json()["connections"][0]["revoked"] is True


def test_expired_requests_codes_tokens_and_wrong_type(mcp_client, db):
    client_id, code, _ = approve(mcp_client)
    code_row = db.get(oauth.MCPCode, oauth.digest(code))
    code_row.expires_at = oauth.now() - timedelta(seconds=1)
    db.commit()
    assert exchange(mcp_client, client_id, code).status_code == 400
    client_id, code, _ = approve(mcp_client)
    tokens = exchange(mcp_client, client_id, code).json()
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["refresh_token"])
    row = db.get(oauth.MCPToken, oauth.digest(tokens["access_token"]))
    row.expires_at = oauth.now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["access_token"])
    response = authorize(mcp_client)
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    db.get(oauth.MCPAuthRequest, ident).expires_at = oauth.now() - timedelta(seconds=1)
    db.commit()
    assert mcp_client.get(f"/api/mcp/authorization-requests/{ident}").status_code == 404


def test_generic_errors_and_bounded_bodies(mcp_client):
    assert mcp_client.post("/oauth/register", content="x" * (oauth.MAX_BODY + 1),
                           headers={"Content-Type": "application/json"}).status_code == 413
    for raw in ['{"redirect_uris":[],"redirect_uris":[]}', '["secret-value"]', '{"bad":"secret-value"}']:
        response = mcp_client.post("/oauth/register", content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 400
        assert "secret-value" not in response.text
    response = mcp_client.post("/oauth/token", content="client_id=a&client_id=b", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 400


def test_malformed_consent_never_reflects_input(mcp_client):
    response = authorize(mcp_client)
    ident = parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]
    path = f"/api/mcp/authorization-requests/{ident}/decision"
    for value in [{"decision": []}, {"decision": {}}, {"decision": "allow", "scopes": [{}]},
                  {"decision": "allow", "scopes": ["finance:read", "finance:read"]}]:
        assert mcp_client.post(path, json=value).status_code == 400


def test_bearer_checks_expiring_grant_and_owner(mcp_client, db):
    client_id, code, _ = approve(mcp_client)
    tokens = exchange(mcp_client, client_id, code).json()
    principal = oauth.verify_bearer_in_session(db, tokens["access_token"])
    grant = db.get(oauth.MCPGrant, principal.grant_id)
    grant.expires_at = oauth.now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["access_token"])
    assert refresh(mcp_client, client_id, tokens["refresh_token"]).status_code == 400
    grant.expires_at = oauth.now() + timedelta(days=1)
    owner = db.get(User, principal.owner_id)
    owner.owner_slot = 2
    db.commit()
    with pytest.raises(HTTPException):
        oauth.verify_bearer_in_session(db, tokens["access_token"])
    assert mcp_client.get("/api/mcp/connections").status_code == 403


def test_persistent_token_limit(mcp_client, db):
    key = oauth.digest("token:testclient")
    db.add(oauth.MCPRateLimit(key=key, count=120, window_start=oauth.now()))
    db.commit()
    response = mcp_client.post("/oauth/token", data={"refresh_token": "synthetic-secret"})
    assert response.status_code == 429
    assert "synthetic-secret" not in response.text
    assert response.headers["retry-after"] == "900"
    db.get(oauth.MCPRateLimit, key).window_start = oauth.now() - timedelta(minutes=16)
    db.commit()
    assert mcp_client.post("/oauth/token", data={}).status_code == 400


@pytest.mark.parametrize("offset_hours", [-7, 0, 1, 2, 5.5])
@pytest.mark.parametrize("seconds_remaining", [-1, 0, 1])
def test_expiration_uses_instant_not_wall_clock(monkeypatch, offset_hours, seconds_remaining):
    fixed = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(oauth, "now", lambda: fixed)
    expires_at = (fixed + timedelta(seconds=seconds_remaining)).astimezone(
        timezone(timedelta(hours=offset_hours)))
    assert oauth.future(expires_at) is (seconds_remaining > 0)


@pytest.mark.parametrize("seconds_remaining", [-1, 0, 1])
def test_naive_sqlite_expiration_assumes_utc(monkeypatch, seconds_remaining):
    fixed = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(oauth, "now", lambda: fixed)
    expires_at = (fixed + timedelta(seconds=seconds_remaining)).replace(tzinfo=None)
    assert oauth.future(expires_at) is (seconds_remaining > 0)


@pytest.mark.parametrize("app_url,expected_endpoint", [
    ("https://finance.example", RESOURCE),
    ("", None),
    ("https://untrusted.example/path?secret=value", None),
    ("http://localhost:8080", None),
])
def test_owner_can_manage_and_revoke_while_disabled(mcp_client, db, monkeypatch, app_url, expected_endpoint):
    client_id, code, _ = approve(mcp_client)
    tokens = exchange(mcp_client, client_id, code).json()
    principal = oauth.verify_bearer_in_session(db, tokens["access_token"])
    pending_response = authorize(mcp_client, client_id)
    pending_id = parse_qs(urlsplit(pending_response.headers["location"]).query)["request_id"][0]
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("APP_URL", app_url)

    result = mcp_client.get("/api/mcp/connections")
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    envelope = result.json()
    assert envelope["enabled"] is False
    assert envelope["endpoint"] == expected_endpoint
    assert envelope["scopes"] == sorted(oauth.SCOPES)
    connection = envelope["connections"][0]
    assert connection["id"] == principal.grant_id
    assert connection["client_id"] == client_id
    assert connection["client_name"] == "Synthetic client"
    assert connection["expires_at"]
    assert connection["revoked"] is False
    assert "secret=value" not in result.text

    consent_path = f"/api/mcp/authorization-requests/{pending_id}"
    assert mcp_client.get(consent_path).status_code == 404
    assert mcp_client.post(consent_path + "/decision", json={"decision": "allow", "scopes": ["finance:read"]}).status_code == 404
    assert db.get(oauth.MCPAuthRequest, pending_id).decided is False
    for path in ["/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp", "/oauth/authorize"]:
        assert mcp_client.get(path).status_code == 404
    assert register(mcp_client).status_code == 404
    assert refresh(mcp_client, client_id, tokens["refresh_token"]).status_code == 404

    revoke_path = f"/api/mcp/connections/{principal.grant_id}"
    assert mcp_client.delete(revoke_path, headers={"X-CSRF-Token": "synthetic-wrong"}).status_code == 403
    assert mcp_client.delete(revoke_path).status_code == 200
    assert mcp_client.get("/api/mcp/connections").json()["connections"][0]["revoked"] is True
    assert all(row.used for row in db.scalars(select(oauth.MCPToken).where(oauth.MCPToken.grant_id == principal.grant_id)))
    mcp_client.cookies.clear()
    assert mcp_client.get("/api/mcp/connections").status_code == 401
    assert mcp_client.delete(revoke_path).status_code == 401


def test_persistent_registration_limit_hashes_ip(mcp_client, db):
    for _ in range(10):
        assert register(mcp_client).status_code == 201
    assert register(mcp_client).status_code == 429
    row = db.scalar(select(oauth.MCPRateLimit))
    assert len(row.key) == 64
    assert "testclient" not in row.key


def peer_request(host, headers=()):
    return Request({"type": "http", "method": "POST", "path": "/oauth/register",
                    "client": (host, 12345), "headers": [(key.lower().encode(), value.encode()) for key, value in headers]})


@pytest.mark.parametrize("trusted", ["", "10.20.0.0/24"])
def test_untrusted_peer_cannot_spoof_rate_identity(monkeypatch, trusted):
    monkeypatch.setenv("MCP_TRUSTED_PROXY_CIDRS", trusted)
    request = peer_request("198.51.100.2", [("X-Forwarded-For", "203.0.113.1"),
                                           ("X-FinSight-Client-IP", "203.0.113.2")])
    assert oauth.rate_limit_peer(request) == "198.51.100.2"


@pytest.mark.parametrize("header", ["", "invalid", "203.0.113.1,203.0.113.2", "203.0.113.1:1234",
                                    " 203.0.113.1", "[2001:db8::1]", "fe80::1%eth0"])
def test_trusted_proxy_invalid_header_falls_back_to_peer(monkeypatch, header):
    monkeypatch.setenv("MCP_TRUSTED_PROXY_CIDRS", "10.20.0.0/24")
    assert oauth.rate_limit_peer(peer_request("10.20.0.2", [("X-FinSight-Client-IP", header)])) == "10.20.0.2"


def test_trusted_proxy_requires_one_custom_header_never_xff(monkeypatch):
    monkeypatch.setenv("MCP_TRUSTED_PROXY_CIDRS", "10.20.0.0/24,2001:db8:1::/48")
    assert oauth.rate_limit_peer(peer_request("10.20.0.2", [("X-Forwarded-For", "203.0.113.2")])) == "10.20.0.2"
    duplicated = [("X-FinSight-Client-IP", "203.0.113.1")] * 2
    assert oauth.rate_limit_peer(peer_request("10.20.0.2", duplicated)) == "10.20.0.2"
    assert oauth.rate_limit_peer(peer_request("10.20.0.2", [("X-FinSight-Client-IP", "203.0.113.1")])) == "203.0.113.1"
    assert oauth.rate_limit_peer(peer_request("2001:db8:1::2", [("X-FinSight-Client-IP", "2001:0db8::3")])) == "2001:db8::3"


@pytest.mark.parametrize("configured", ["invalid", "10.20.0.0/24,invalid", "10.20.0.0/24,", "10.20.0.2/24"])
def test_invalid_proxy_configuration_ignores_header(monkeypatch, configured):
    monkeypatch.setenv("MCP_TRUSTED_PROXY_CIDRS", configured)
    request = peer_request("10.20.0.2", [("X-FinSight-Client-IP", "203.0.113.1")])
    assert oauth.rate_limit_peer(request) == "10.20.0.2"


def test_trusted_proxy_uses_separate_persistent_client_buckets(mcp_client, db, monkeypatch):
    monkeypatch.setenv("MCP_TRUSTED_PROXY_CIDRS", "10.20.0.0/24")
    with TestClient(mcp_client.app, client=("10.20.0.2", 12345)) as proxy:
        for address in ["203.0.113.1", "203.0.113.2"]:
            proxy.headers["X-FinSight-Client-IP"] = address
            proxy.headers["X-Forwarded-For"] = "spoofed-and-ignored"
            for _ in range(10):
                assert register(proxy).status_code == 201
            assert register(proxy).status_code == 429
    assert {row.key for row in db.scalars(select(oauth.MCPRateLimit))} == {
        oauth.digest("register:203.0.113.1"), oauth.digest("register:203.0.113.2")}


def test_sqlite_concurrent_code_redemption_is_single_use(tmp_path, monkeypatch):
    """Independent connections/read snapshots race at the code consumption boundary."""
    monkeypatch.setenv("MCP_ENABLED", "true")
    monkeypatch.setenv("APP_URL", "https://finance.example")
    engine = create_engine("sqlite:///" + str(tmp_path / "synthetic-oauth-race.db"),
                           connect_args={"check_same_thread": False})
    oauth.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(email="race@example.test", password_hash="unused", owner_slot=1)
        client = oauth.MCPClient(name="Synthetic race", redirect_uris=[REDIRECT], scopes="finance:read")
        db.add_all([user, client])
        db.flush()
        grant = oauth.MCPGrant(user_id=user.id, client_id=client.id, resource=RESOURCE,
                               scopes="finance:read", expires_at=oauth.now() + timedelta(days=1))
        db.add(grant)
        db.flush()
        code = "synthetic-code-" + "a" * 32
        db.add(oauth.MCPCode(id=oauth.digest(code), grant_id=grant.id, redirect_uri=REDIRECT,
                             challenge=CHALLENGE, expires_at=oauth.now() + timedelta(minutes=2)))
        db.commit()
        client_id = client.id

    def session_dependency():
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(oauth.router)
    app.dependency_overrides[get_db] = session_dependency
    barrier = Barrier(2)
    original = oauth.locked_grant

    def synchronized_grant(db, ident):
        result = original(db, ident)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(oauth, "locked_grant", synchronized_grant)

    def redeem(_):
        with TestClient(app) as client:
            return exchange(client, client_id, code).status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sorted(executor.map(redeem, range(2))) == [200, 400]
        with factory() as db:
            tokens = list(db.scalars(select(oauth.MCPToken)))
            assert len(tokens) == 2
            assert all(token.used for token in tokens)
            assert db.scalar(select(oauth.MCPGrant)).revoked is True
    finally:
        engine.dispose()


def test_frozen_migration_matches_models():
    path = Path(__file__).parents[1] / "migrations/versions/0002_mcp_oauth.py"
    spec = importlib.util.spec_from_file_location("frozen_mcp_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0001"
    metadata = migration.schema()
    for name, table in metadata.tables.items():
        if name == "users":
            continue
        model = oauth.Base.metadata.tables[name]
        assert set(table.columns.keys()) == set(model.columns.keys())
        for column in table.columns:
            assert str(column.type) == str(model.c[column.name].type)
            assert column.nullable == model.c[column.name].nullable
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    assert "mcp_tokens" in inspect(engine).get_table_names()
    metadata.drop_all(engine)
    engine.dispose()
