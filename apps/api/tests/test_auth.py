from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth import hasher
from app.models import Session, User


BODY = {"bootstrap_secret": "synthetic-bootstrap-secret", "email": "synthetic@example.test", "password": "synthetic-long-password"}


def test_bootstrap_auth_csrf_expiry(client, db):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/status").json() == {"initialized": False, "authenticated": False}
    assert client.get("/api/accounts").status_code == 401
    assert client.post("/api/auth/setup", json={**BODY, "bootstrap_secret": "synthetic-wrong"}).status_code == 403
    assert client.post("/api/auth/setup", json=BODY, headers={"origin": "https://attacker.test"}).status_code == 403
    setup = client.post("/api/auth/setup", json=BODY)
    assert setup.status_code == 201
    assert "httponly" in setup.headers["set-cookie"].lower()
    assert "samesite=strict" in setup.headers["set-cookie"].lower()
    assert hasher.verify(db.scalar(select(User)).password_hash, BODY["password"])
    assert client.post("/api/auth/setup", json=BODY).status_code == 409
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/buckets", json={"name": "Synthetic"}).status_code == 403
    csrf = setup.json()["csrf_token"]
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": BODY["email"], "password": "synthetic-wrong-password"}).status_code == 401
    login = client.post("/api/auth/login", json=BODY)
    assert login.status_code == 200
    session = db.scalar(select(Session))
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_rate_limit_persistent(client):
    for _ in range(10):
        assert client.post("/api/auth/login", json={"email": "nobody@test", "password": "synthetic-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@test", "password": "synthetic-password"}).status_code == 429


def test_secure_cookie_config(client):
    from app.config import settings
    settings.cookie_secure = True
    response = client.post("/api/auth/setup", json=BODY)
    assert "; Secure" in response.headers["set-cookie"]
    settings.cookie_secure = False


def test_streaming_and_declared_request_body_limits(owner):
    assert owner.patch("/api/settings", content=b"x" * 70000, headers={"Content-Type": "application/json"}).status_code == 413

    def chunks():
        for _ in range(10):
            yield b"x" * 10000
    # A generator has no Content-Length, exercising the streaming guard.
    assert owner.patch("/api/settings", content=chunks(), headers={"Content-Type": "application/json"}).status_code == 413


def test_unexpected_errors_are_not_logged_or_echoed(owner, monkeypatch, caplog):
    import app.routes
    def fail(*args, **kwargs):
        raise ValueError("synthetic-sensitive-error-content")
    monkeypatch.setattr(app.routes, "overview", fail)
    response = owner.get("/api/overview")
    assert response.status_code == 503
    assert "synthetic-sensitive-error-content" not in response.text
    assert "synthetic-sensitive-error-content" not in caplog.text
