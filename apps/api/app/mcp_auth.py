"""Owner-approved OAuth for remote MCP; no client registration implies consent.

This router has absolute paths and MUST NOT inherit the cookie-CSRF dependency.
The two cookie-authenticated mutation endpoints apply that dependency explicitly.
"""
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, delete, func, select, text, update
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.responses import JSONResponse, RedirectResponse

from .auth import current_user, require_csrf
from .db import Base, SessionLocal, get_db
from .models import User


SCOPES = frozenset({"finance:read", "finance:transactions"})
DISCLOSURE = ("Approving allows this external client to retrieve your financial data from this server. "
              "The data leaves your local FinSight server and may be stored or processed by the client. "
              "finance:read permits aggregate financial views; finance:transactions additionally permits "
              "individual transaction details. You can revoke access in MCP connections.")
ACCESS_SECONDS = 600
REFRESH_SECONDS = 30 * 24 * 3600
REQUEST_SECONDS = 600
MAX_BODY = 16384


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def future(value):
    utc_value = (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
                 else value.astimezone(timezone.utc))
    return utc_value > now()


class MCPClient(Base):
    __tablename__ = "mcp_clients"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    redirect_uris: Mapped[list] = mapped_column(JSON)
    scopes: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MCPAuthRequest(Base):
    __tablename__ = "mcp_auth_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("mcp_clients.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    resource: Mapped[str] = mapped_column(String(2048))
    scopes: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(1024))
    challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided: Mapped[bool] = mapped_column(Boolean, default=False)


class MCPGrant(Base):
    __tablename__ = "mcp_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("mcp_clients.id"), index=True)
    resource: Mapped[str] = mapped_column(String(2048))
    scopes: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class MCPCode(Base):
    __tablename__ = "mcp_codes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("mcp_grants.id"), index=True)
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    challenge: Mapped[str] = mapped_column(String(43))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class MCPToken(Base):
    __tablename__ = "mcp_tokens"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    grant_id: Mapped[str] = mapped_column(ForeignKey("mcp_grants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    scopes: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[bool] = mapped_column(Boolean, default=False)


class MCPRateLimit(Base):
    __tablename__ = "mcp_rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer)


@dataclass(frozen=True)
class MCPPrincipal:
    owner_id: str
    scopes: frozenset[str]
    grant_id: str


def enabled():
    return os.getenv("MCP_ENABLED", "false").lower() in {"true", "1", "yes"}


def loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def safe_url(value, *, origin=False):
    """Validate without network access, decoding, or redirect normalization."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value or "#" in value:
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        _ = parts.port
    except ValueError:
        return False
    if not host or parts.username is not None or parts.password is not None:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if (len(host) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                                      for label in host.rstrip(".").split("."))):
            return False
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback(host)):
        return False
    if origin and (parts.path not in {"", "/"} or parts.query):
        return False
    try:
        if not origin and any(key in {"code", "error", "state", "iss"}
                              for key, _ in parse_qsl(parts.query, max_num_fields=50)):
            return False
    except ValueError:
        return False
    return True


def issuer():
    value = os.getenv("APP_URL", "")
    if not safe_url(value, origin=True):
        raise HTTPException(503, "MCP configuration unavailable")
    # Clear-text issuer is permitted only when explicitly running development/test.
    if urlsplit(value).scheme == "http" and os.getenv("APP_ENV", "production").lower() not in {"development", "test"}:
        raise HTTPException(503, "MCP configuration unavailable")
    return value.rstrip("/")


def resource_url():
    return issuer() + "/mcp"


def available():
    if not enabled():
        raise HTTPException(404, "Not found")
    issuer()


router = APIRouter(tags=["mcp-auth"])


def oauth_error(error="invalid_request", status=400):
    # Never reflect request values, tokens, or validation input in errors.
    return JSONResponse({"error": error}, status_code=status,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def informational_metadata(data):
    """Accept standard DCR display metadata without fetching, storing or trusting it."""
    for key in ("client_uri", "logo_uri", "policy_uri", "tos_uri"):
        if key in data and (not safe_url(data[key]) or urlsplit(data[key]).scheme != "https"):
            return False
    for key, maximum in (("software_id", 128), ("software_version", 64)):
        if key in data and (not isinstance(data[key], str) or not 1 <= len(data[key]) <= maximum
                            or any(ord(c) < 32 or ord(c) == 127 for c in data[key])):
            return False
    if "contacts" in data:
        contacts = data["contacts"]
        if (not isinstance(contacts, list) or not 1 <= len(contacts) <= 8
                or any(not isinstance(value, str) or len(value) > 254
                       or not re.fullmatch(r"[^\s@\x00-\x1f\x7f]+@[^\s@\x00-\x1f\x7f]+", value)
                       for value in contacts)):
            return False
    return True


async def body_fields(request, *, form=False):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "Request too large")
    content_type = request.headers.get("content-type", "").split(";")[0].lower()
    try:
        if form and content_type == "application/x-www-form-urlencoded":
            pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
            if len({key for key, _ in pairs}) != len(pairs):
                return None
            data = dict(pairs)
        elif content_type == "application/json":
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = value
                return result
            data = json.loads(raw, object_pairs_hook=unique)
        else:
            return None
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(data, dict) or len(data) > 20:
        return None
    # Unknown DCR extensions are ignored, but they cannot bypass parser bounds.
    pending = [(data, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 8 or nodes > 256:
            return None
        if isinstance(value, dict):
            if len(value) > 20:
                return None
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if len(value) > 64:
                return None
            pending.extend((child, depth + 1) for child in value)
    return data


def scopes_value(value, default="finance:read"):
    if value is None:
        value = default
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        return None
    scopes = value.split(" ")
    if not scopes or any(item not in SCOPES for item in scopes) or len(scopes) != len(set(scopes)):
        return None
    return " ".join(sorted(scopes))


def rate_limit_peer(request):
    """Use proxy-supplied identity only from an explicitly trusted actual peer."""
    host = request.client.host if request.client else "local"
    try:
        if "%" in host:
            return host
        peer = ipaddress.ip_address(host)
    except ValueError:
        return host
    configured = os.getenv("MCP_TRUSTED_PROXY_CIDRS", "")
    if not configured:
        return str(peer)
    try:
        entries = configured.split(",")
        if len(configured) > 4096 or len(entries) > 64:
            return str(peer)
        networks = [ipaddress.ip_network(entry.strip()) for entry in entries]
    except ValueError:
        # One invalid entry disables all forwarded identity trust, not just itself.
        return str(peer)
    if not any(peer in network for network in networks):
        return str(peer)
    headers = request.headers.getlist("x-finsight-client-ip")
    if len(headers) != 1 or "%" in headers[0]:
        return str(peer)
    try:
        return str(ipaddress.ip_address(headers[0]))
    except ValueError:
        return str(peer)


def rate_limit(request, db, endpoint):
    # X-Forwarded-For is never trusted. Persist only opaque per-endpoint IP hashes.
    key = digest(endpoint + ":" + rate_limit_peer(request))
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(key[:16], 16) % (2 ** 63)})
    elif db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))
    cutoff = now() - timedelta(minutes=15)
    db.execute(delete(MCPRateLimit).where(MCPRateLimit.window_start < cutoff))
    row = db.get(MCPRateLimit, key)
    maximum = {"register": 10, "authorize": 60, "token": 120}[endpoint]
    if row and row.count >= maximum:
        db.commit()
        raise HTTPException(429, "Too many requests", headers={"Retry-After": "900"})
    if row:
        row.count += 1
    else:
        db.add(MCPRateLimit(key=key, count=1, window_start=now()))
    db.commit()


@router.get("/.well-known/oauth-protected-resource/mcp", dependencies=[Depends(available)])
def protected_resource():
    return {"resource": resource_url(), "authorization_servers": [issuer()],
            "scopes_supported": sorted(SCOPES), "bearer_methods_supported": ["header"],
            "resource_name": "FinSight read-only financial data"}


@router.get("/.well-known/oauth-authorization-server", dependencies=[Depends(available)])
def authorization_server():
    base = issuer()
    return {"issuer": base, "authorization_endpoint": base + "/oauth/authorize",
            "authorization_response_iss_parameter_supported": True,
            "token_endpoint": base + "/oauth/token", "registration_endpoint": base + "/oauth/register",
            "response_types_supported": ["code"], "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"], "scopes_supported": sorted(SCOPES)}


@router.post("/oauth/register", dependencies=[Depends(available)])
async def register(request: Request, db: Session = Depends(get_db)):
    rate_limit(request, db, "register")
    data = await body_fields(request)
    # RFC 7591 requires ignoring unrecognized registration metadata. Only known
    # fields influence validation/registration; extensions are never persisted.
    if data is None or not informational_metadata(data):
        return oauth_error("invalid_client_metadata")
    redirects = data.get("redirect_uris")
    name = data.get("client_name", "MCP client")
    scopes = scopes_value(data.get("scope"))
    if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 8
            or not all(safe_url(uri) for uri in redirects)
            or len(set(redirects)) != len(redirects)
            or not isinstance(name, str) or not 1 <= len(name) <= 160
            or any(ord(c) < 32 for c in name)
            or data.get("token_endpoint_auth_method", "none") != "none"
            or data.get("response_types", ["code"]) != ["code"]
            or data.get("grant_types", ["authorization_code", "refresh_token"]) not in
               (["authorization_code"], ["authorization_code", "refresh_token"], ["refresh_token", "authorization_code"])
            or scopes is None):
        return oauth_error("invalid_client_metadata")
    # Scope metadata describes capabilities, not an approval. If omitted, allow requesting either.
    client = MCPClient(name=name, redirect_uris=redirects,
                       scopes=scopes if "scope" in data else " ".join(sorted(SCOPES)))
    db.add(client)
    db.commit()
    return JSONResponse({"client_id": client.id, "client_id_issued_at": int(client.created_at.timestamp()),
                         "client_name": client.name, "redirect_uris": redirects,
                         "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                         "response_types": ["code"], "scope": client.scopes}, status_code=201,
                        headers={"Cache-Control": "no-store"})


@router.get("/oauth/authorize", dependencies=[Depends(available)])
def authorize(request: Request, db: Session = Depends(get_db)):
    rate_limit(request, db, "authorize")
    params = request.query_params
    allowed = {"client_id", "redirect_uri", "response_type", "code_challenge", "code_challenge_method", "resource", "scope", "state"}
    if (len(request.scope.get("query_string", b"")) > MAX_BODY or set(params) - allowed
            or any(len(params.getlist(key)) != 1 for key in params)):
        return oauth_error()
    client_id = params.get("client_id", "")
    client = db.get(MCPClient, client_id) if len(client_id) <= 36 else None
    redirect = params.get("redirect_uri", "")
    challenge = params.get("code_challenge", "")
    scopes = scopes_value(params.get("scope"))
    state = params.get("state", "")
    if (not client or redirect not in client.redirect_uris or not safe_url(redirect)
            or params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge)
            or params.get("resource") != resource_url() or len(state) > 1024
            or any(ord(c) < 32 for c in state)):
        return oauth_error()
    if scopes is None or not set(scopes.split()).issubset(client.scopes.split()):
        return oauth_error("invalid_scope")
    pending = MCPAuthRequest(client_id=client.id, redirect_uri=redirect, resource=resource_url(),
                             scopes=scopes, state=state, challenge=challenge,
                             expires_at=now() + timedelta(seconds=REQUEST_SECONDS))
    db.add(pending)
    db.commit()
    return RedirectResponse(issuer() + "/mcp/authorize?" + urlencode({"request_id": pending.id}), status_code=302,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


def owner(user: User = Depends(current_user)):
    if user.owner_slot != 1:
        raise HTTPException(403, "Owner required")
    return user


def pending_request(db, ident, *, lock=False):
    try:
        if str(UUID(ident)) != ident:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, "Not found") from None
    query = select(MCPAuthRequest).where(MCPAuthRequest.id == ident).execution_options(populate_existing=True)
    item = db.scalar(query.with_for_update() if lock else query)
    if not item or item.decided or not future(item.expires_at) or item.resource != resource_url():
        raise HTTPException(404, "Authorization request unavailable")
    client = db.get(MCPClient, item.client_id)
    if not client or item.redirect_uri not in client.redirect_uris or not safe_url(item.redirect_uri):
        raise HTTPException(400, "Authorization request unavailable")
    return item, client


@router.get("/api/mcp/authorization-requests/{ident}", dependencies=[Depends(available), Depends(no_store)])
def authorization_request(ident: str, db: Session = Depends(get_db), user=Depends(owner)):
    item, client = pending_request(db, ident)
    return {"id": item.id, "client_id": client.id, "client_name": client.name,
            "redirect_uri": item.redirect_uri, "resource": item.resource,
            "scopes": item.scopes.split(), "expires_at": item.expires_at,
            "disclosure": DISCLOSURE}


def callback_url(item, **values):
    parts = urlsplit(item.redirect_uri)
    # Preserve the registered query byte-for-byte; registration rejects response keys.
    query = list(values.items())
    if item.state:
        query.append(("state", item.state))
    query.append(("iss", issuer()))
    combined = (parts.query + "&" if parts.query else "") + urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, combined, ""))


@router.post("/api/mcp/authorization-requests/{ident}/decision", dependencies=[Depends(available), Depends(require_csrf), Depends(no_store)])
async def decision(ident: str, request: Request, db: Session = Depends(get_db), user=Depends(owner)):
    data = await body_fields(request)
    if (data is None or set(data) - {"decision", "scopes"}
            or not isinstance(data.get("decision"), str) or data["decision"] not in {"allow", "deny"}):
        return oauth_error()
    item, client = pending_request(db, ident, lock=True)
    selected = data.get("scopes", [])
    if (not isinstance(selected, list) or len(selected) > 2
            or any(not isinstance(scope, str) or scope not in item.scopes.split() for scope in selected)
            or len(set(selected)) != len(selected)
            or (data["decision"] == "allow" and not selected)):
        return oauth_error("invalid_scope")
    claimed = db.execute(update(MCPAuthRequest).where(MCPAuthRequest.id == ident,
                         MCPAuthRequest.decided.is_(False), MCPAuthRequest.expires_at > now())
                         .values(decided=True).execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        db.rollback()
        raise HTTPException(409, "Authorization request unavailable")
    if data["decision"] == "deny":
        redirect = callback_url(item, error="access_denied")
    else:
        grant = MCPGrant(user_id=user.id, client_id=client.id, resource=item.resource,
                         scopes=" ".join(sorted(selected)), expires_at=now() + timedelta(seconds=REFRESH_SECONDS))
        db.add(grant)
        db.flush()
        code = secrets.token_urlsafe(32)
        db.add(MCPCode(id=digest(code), grant_id=grant.id, redirect_uri=item.redirect_uri,
                       challenge=item.challenge, expires_at=now() + timedelta(seconds=120)))
        redirect = callback_url(item, code=code)
    db.commit()
    return {"redirect_url": redirect}


def locked_grant(db, ident):
    return db.scalar(select(MCPGrant).where(MCPGrant.id == ident).with_for_update()
                     .execution_options(populate_existing=True))


def revoke_family(db, grant):
    # The caller holds the grant row lock on PostgreSQL. The grant flag is also
    # authoritative on every bearer check, including any concurrent SQLite issue.
    grant.revoked = True
    db.execute(update(MCPToken).where(MCPToken.grant_id == grant.id).values(used=True))


def active_grant(db, grant):
    return (grant is not None and not grant.revoked and future(grant.expires_at)
            and grant.resource == resource_url()
            and db.scalar(select(User.id).where(User.id == grant.user_id, User.owner_slot == 1)) is not None)


def issue_tokens(db, grant, scopes):
    access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    db.add(MCPToken(id=digest(access), grant_id=grant.id, kind="access", scopes=scopes,
                    expires_at=now() + timedelta(seconds=ACCESS_SECONDS)))
    db.add(MCPToken(id=digest(refresh), grant_id=grant.id, kind="refresh", scopes=scopes,
                    expires_at=grant.expires_at))
    db.commit()
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_SECONDS,
                         "refresh_token": refresh, "scope": scopes},
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.post("/oauth/token", dependencies=[Depends(available)])
async def token(request: Request, db: Session = Depends(get_db)):
    rate_limit(request, db, "token")
    data = await body_fields(request, form=True)
    allowed = {"grant_type", "client_id", "code", "redirect_uri", "code_verifier", "refresh_token", "resource", "scope"}
    if (data is None or set(data) - allowed or request.headers.get("authorization")
            or any(not isinstance(v, str) or len(v) > 2048 for v in data.values())):
        return oauth_error()
    if data.get("resource") != resource_url():
        return oauth_error("invalid_target")
    kind = data.get("grant_type")
    if kind not in {"authorization_code", "refresh_token"}:
        return oauth_error("unsupported_grant_type")
    if kind == "authorization_code":
        code = db.get(MCPCode, digest(data.get("code", "")))
        grant = locked_grant(db, code.grant_id) if code else None
        verifier = data.get("code_verifier", "")
        if (not code or not active_grant(db, grant)
                or data.get("client_id") != grant.client_id or data.get("redirect_uri") != code.redirect_uri
                or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
                or not secrets.compare_digest(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                                              .rstrip(b"=").decode(), code.challenge)
                or "scope" in data or "refresh_token" in data):
            return oauth_error("invalid_grant")
        if code.used:
            # Binding and PKCE checks must precede replay revocation, otherwise a
            # guessed client or an intercepted code becomes a grant-revocation DoS.
            revoke_family(db, grant)
            db.commit()
            return oauth_error("invalid_grant")
        if not future(code.expires_at):
            return oauth_error("invalid_grant")
        claimed = db.execute(update(MCPCode).where(MCPCode.id == code.id, MCPCode.used.is_(False),
                             MCPCode.expires_at > now()).values(used=True)
                             .execution_options(synchronize_session=False)).rowcount
        scopes = grant.scopes
    else:
        refresh = db.get(MCPToken, digest(data.get("refresh_token", "")))
        grant = locked_grant(db, refresh.grant_id) if refresh else None
        if refresh is not None:
            # Another request may have rotated it while this request waited for
            # the grant lock. Reload after locking to detect replay, not just a
            # failed compare-and-swap (also avoids identity-map stale reads).
            db.refresh(refresh)
        if (not refresh or refresh.kind != "refresh" or not active_grant(db, grant)
                or data.get("client_id") != grant.client_id or not future(refresh.expires_at)
                or any(key in data for key in {"code", "redirect_uri", "code_verifier"})):
            return oauth_error("invalid_grant")
        if refresh.used:
            # Replayed refresh tokens invalidate the complete authorization family.
            revoke_family(db, grant)
            db.commit()
            return oauth_error("invalid_grant")
        scopes = scopes_value(data.get("scope"), refresh.scopes)
        if scopes is None or not set(scopes.split()).issubset(refresh.scopes.split()):
            return oauth_error("invalid_scope")
        claimed = db.execute(update(MCPToken).where(MCPToken.id == refresh.id, MCPToken.used.is_(False),
                             MCPToken.expires_at > now()).values(used=True)
                             .execution_options(synchronize_session=False)).rowcount
    if claimed != 1:
        # A concurrent redemption/rotation can win the conditional update even if
        # our earlier read saw unused credentials. All binding checks precede this.
        credential = refresh if kind == "refresh_token" else code
        db.refresh(credential)
        if credential.used:
            revoke_family(db, grant)
            db.commit()
            return oauth_error("invalid_grant")
        db.rollback()
        return oauth_error("invalid_grant")
    return issue_tokens(db, grant, scopes)


def verify_bearer_in_session(db, token: str) -> MCPPrincipal:
    available()
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise HTTPException(401, "Invalid bearer token")
    # A fresh query is intentional: never trust a cached grant following revocation.
    row = db.scalar(select(MCPToken).where(MCPToken.id == digest(token)).execution_options(populate_existing=True))
    grant = db.scalar(select(MCPGrant).where(MCPGrant.id == row.grant_id)
                      .execution_options(populate_existing=True)) if row else None
    if not row or row.kind != "access" or row.used or not future(row.expires_at) or not active_grant(db, grant):
        raise HTTPException(401, "Invalid bearer token")
    scopes = frozenset(row.scopes.split())
    if not scopes or not scopes.issubset(SCOPES) or not scopes.issubset(grant.scopes.split()):
        raise HTTPException(401, "Invalid bearer token")
    return MCPPrincipal(owner_id=grant.user_id, scopes=scopes, grant_id=grant.id)


def verify_bearer(token: str, resource: str | None = None) -> MCPPrincipal:
    available()
    if resource is not None and resource != resource_url():
        raise HTTPException(401, "Invalid bearer token")
    with SessionLocal() as db:
        return verify_bearer_in_session(db, token)


@router.get("/api/mcp/connections", dependencies=[Depends(no_store)])
def connections(db: Session = Depends(get_db), user=Depends(owner)):
    # Operators must still be able to inspect/revoke grants while MCP is off or
    # its issuer configuration is broken. Never reflect an unvalidated APP_URL.
    try:
        endpoint = resource_url()
    except HTTPException:
        endpoint = None
    rows = db.execute(select(MCPGrant, MCPClient).join(MCPClient, MCPGrant.client_id == MCPClient.id)
                      .where(MCPGrant.user_id == user.id).order_by(MCPGrant.created_at.desc()).limit(200))
    return {"enabled": enabled(), "endpoint": endpoint, "scopes": sorted(SCOPES),
            "connections": [{"id": grant.id, "client_id": client.id, "client_name": client.name,
                             "scopes": grant.scopes.split(), "resource": grant.resource,
                             "created_at": grant.created_at, "expires_at": grant.expires_at,
                             "revoked": grant.revoked} for grant, client in rows]}


@router.delete("/api/mcp/connections/{ident}", dependencies=[Depends(require_csrf), Depends(no_store)])
def revoke(ident: str, db: Session = Depends(get_db), user=Depends(owner)):
    if len(ident) > 36:
        raise HTTPException(404, "Not found")
    grant = locked_grant(db, ident)
    if not grant or grant.user_id != user.id:
        raise HTTPException(404, "Not found")
    revoke_family(db, grant)
    db.commit()
    return {"ok": True}
