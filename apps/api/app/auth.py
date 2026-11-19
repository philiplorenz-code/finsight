import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from .config import settings
from .db import get_db
from .models import LoginAttempt, Session, User

router = APIRouter(prefix="/auth", tags=["auth"])
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))
COOKIE = "finsight_session"


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def session_for(request, db):
    token = request.cookies.get(COOKIE, "")
    if not token:
        return None
    session = db.get(Session, token_hash(token))
    if session and session.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc):
        return session
    return None


def current_user(request: Request, db: DBSession = Depends(get_db)):
    session = session_for(request, db)
    user = db.get(User, session.user_id) if session else None
    if not user:
        raise HTTPException(401, "Authentication required")
    request.state.session = session
    return user


def require_csrf(request: Request, db: DBSession = Depends(get_db)):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.url.path in {"/api/auth/setup", "/api/auth/login"}:
        # JSON-only endpoints and origin checking prevent login CSRF.
        origin = request.headers.get("origin")
        own_origin = str(request.base_url).rstrip("/")
        if origin and origin != own_origin and origin not in settings.allowed_origins:
            raise HTTPException(403, "Origin not allowed")
        return
    session = session_for(request, db)
    if not session:
        raise HTTPException(401, "Authentication required")
    csrf = request.headers.get("x-csrf-token", "")
    if not secrets.compare_digest(csrf, session.csrf_token):
        raise HTTPException(403, "Invalid CSRF token")


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=1024)


class Setup(Credentials):
    bootstrap_secret: str = Field(max_length=1024)


def rate_limit(request, db):
    # Persisted, opaque per-client counters; do not trust forwarded headers.
    key = token_hash(request.client.host if request.client else "local")
    if db.get_bind().dialect.name == "postgresql":
        # Per-client transaction lock makes count + insert an atomic decision
        # across API replicas without keeping process-local state.
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int(key[:16], 16) % (2 ** 63)})
    elif db.get_bind().dialect.name == "sqlite" and not db.in_transaction():
        db.execute(text("BEGIN IMMEDIATE"))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))
    count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.key == key))
    if count >= 10:
        db.commit()
        raise HTTPException(429, "Too many attempts; try again later")
    db.add(LoginAttempt(key=key))
    db.commit()


def sign_in(user, db, response):
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    db.add(Session(id=token_hash(token), user_id=user.id, csrf_token=csrf,
                   expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", max_age=settings.session_hours * 3600, path="/")
    return {"id": user.id, "email": user.email, "csrf_token": csrf}


@router.get("/status")
def status(request: Request, db: DBSession = Depends(get_db)):
    return {"initialized": db.scalar(select(User.id).limit(1)) is not None,
            "authenticated": session_for(request, db) is not None}


@router.post("/setup", status_code=201)
def setup(body: Setup, request: Request, response: Response, db: DBSession = Depends(get_db)):
    rate_limit(request, db)
    if not settings.bootstrap_secret or not secrets.compare_digest(body.bootstrap_secret, settings.bootstrap_secret):
        raise HTTPException(403, "Setup not authorized")
    if db.scalar(select(User.id).limit(1)):
        raise HTTPException(409, "Installation already initialized")
    user = User(email=body.email.strip().lower(), password_hash=hasher.hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Installation already initialized") from None
    return sign_in(user, db, response)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: DBSession = Depends(get_db)):
    rate_limit(request, db)
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    try:
        valid = hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not user or not valid:
        raise HTTPException(401, "Invalid credentials")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(body.password)
    return sign_in(user, db, response)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class EmailChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    email: str = Field(min_length=3, max_length=254)


def require_current_password(user, password):
    try:
        valid = hasher.verify(user.password_hash, password)
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(403, "Current password is incorrect")


@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    rate_limit(request, db)
    require_current_password(user, body.current_password)
    if body.new_password == body.current_password:
        raise HTTPException(422, "The new password must differ from the current one")
    user.password_hash = hasher.hash(body.new_password)
    # Other devices/browsers must sign in again with the new password; this session stays valid.
    revoked = db.execute(delete(Session).where(Session.user_id == user.id, Session.id != request.state.session.id)).rowcount
    db.commit()
    return {"ok": True, "sessions_revoked": revoked}


@router.post("/change-email")
def change_email(body: EmailChange, request: Request, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    rate_limit(request, db)
    require_current_password(user, body.current_password)
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
        raise HTTPException(422, "Enter a valid e-mail address")
    user.email = email
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail address already in use") from None
    return {"email": email}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "csrf_token": request.state.session.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: DBSession = Depends(get_db)):
    db.delete(request.state.session)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
