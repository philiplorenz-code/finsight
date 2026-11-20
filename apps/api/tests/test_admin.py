"""Local password reset command (synthetic credentials only)."""
import pytest

import app.admin as admin
from app.auth import hasher
from app.models import Session, User


def test_reset_password_rehashes_and_ends_sessions(owner, db, monkeypatch):
    monkeypatch.setattr(admin, "SessionLocal", lambda: db.__class__(bind=db.get_bind()))
    email, ended = admin.reset_password(None, "synthetic-new-password-1")
    db.expire_all()
    user = db.query(User).one()
    assert email == "synthetic@example.test" and ended >= 1 and db.query(Session).count() == 0
    assert hasher.verify(user.password_hash, "synthetic-new-password-1")
    with pytest.raises(ValueError):
        admin.reset_password(None, "synthetic")
    with pytest.raises(LookupError):
        admin.reset_password("nobody@example.test", "synthetic-new-password-2")
