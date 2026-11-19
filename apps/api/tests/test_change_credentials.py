"""Changing the password and e-mail: current password required, other sessions revoked, rate limited."""
from fastapi.testclient import TestClient

from app.main import app
from app.models import User

OLD = "synthetic-long-password"
NEW = "another-synthetic-long-password"
EMAIL = "synthetic@example.test"


def login(email=EMAIL, password=OLD):
    other = TestClient(app)
    response = other.post("/api/auth/login", json={"email": email, "password": password})
    return other, response


def test_wrong_current_password_and_weak_new_password_are_rejected(owner):
    assert owner.post("/api/auth/change-password", json={"current_password": "nope-nope-nope", "new_password": NEW}).status_code == 403
    assert owner.post("/api/auth/change-password", json={"current_password": OLD, "new_password": "short"}).status_code == 422
    assert owner.post("/api/auth/change-password", json={"current_password": OLD, "new_password": OLD}).status_code == 422
    assert login()[1].status_code == 200, "the old password still works after rejected attempts"


def test_password_change_revokes_other_sessions_but_keeps_this_one(owner):
    other, response = login()
    assert response.status_code == 200 and other.get("/api/auth/me").status_code == 200
    result = owner.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW})
    assert result.status_code == 200 and result.json()["sessions_revoked"] == 1
    assert owner.get("/api/auth/me").status_code == 200, "this session stays signed in"
    assert other.get("/api/auth/me").status_code == 401, "the other session was revoked"
    assert login(password=OLD)[1].status_code == 401
    assert login(password=NEW)[1].status_code == 200


def test_email_change_needs_the_password_and_a_valid_unique_address(owner, db):
    assert owner.post("/api/auth/change-email", json={"current_password": "wrong-wrong-wrong", "email": "new@example.test"}).status_code == 403
    assert owner.post("/api/auth/change-email", json={"current_password": OLD, "email": "not an address"}).status_code == 422
    db.add(User(owner_slot=2, email="taken@example.test", password_hash="not-for-login"))
    db.commit()
    assert owner.post("/api/auth/change-email", json={"current_password": OLD, "email": " TAKEN@example.test "}).status_code == 409
    ok = owner.post("/api/auth/change-email", json={"current_password": OLD, "email": "  New.Name@Example.Test "})
    assert ok.status_code == 200 and ok.json()["email"] == "new.name@example.test"
    assert owner.get("/api/auth/me").json()["email"] == "new.name@example.test"
    assert login(email="new.name@example.test")[1].status_code == 200
    assert login(email=EMAIL)[1].status_code == 401


def test_repeated_wrong_passwords_are_rate_limited(owner):
    codes = [owner.post("/api/auth/change-password", json={"current_password": "wrong-wrong-wrong", "new_password": NEW}).status_code for _ in range(14)]
    assert 429 in codes and codes[0] == 403


def test_credential_changes_require_login_and_csrf(client, owner):
    anonymous = TestClient(app)
    assert anonymous.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW}).status_code in {401, 403}
    assert anonymous.post("/api/auth/change-email", json={"current_password": OLD, "email": "a@b.test"}).status_code in {401, 403}
    del owner.headers["X-CSRF-Token"]
    assert owner.post("/api/auth/change-password", json={"current_password": OLD, "new_password": NEW}).status_code == 403
