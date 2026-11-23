"""Paperless-ngx connector against a mocked Paperless. Synthetic data only."""
import json

import httpx
import pytest

import app.paperless as pl

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image" * 10


@pytest.fixture
def paperless(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("Authorization") != "Token synthetic-paperless-token":
            return httpx.Response(401)
        if request.url.path == "/api/documents/post_document/":
            return httpx.Response(200, json="synthetic-task-1")
        if request.url.path == "/api/documents/":
            return httpx.Response(200, json={"count": 1, "results": [{"id": 7, "title": "Synthetic Rechnung", "created": "2026-10-02"}]})
        return httpx.Response(404)

    monkeypatch.setattr(pl, "transport", httpx.MockTransport(handler))
    monkeypatch.setenv("PAPERLESS_URL", "http://paperless.test:8000")
    monkeypatch.setenv("PAPERLESS_TOKEN", "synthetic-paperless-token")
    return seen


def test_not_configured(owner, monkeypatch):
    monkeypatch.delenv("PAPERLESS_URL", raising=False)
    monkeypatch.delenv("PAPERLESS_TOKEN", raising=False)
    assert owner.get("/api/paperless/status").json() == {"configured": False, "reachable": False}
    assert owner.get("/api/paperless/documents", params={"q": "synthetic"}).status_code == 409


def test_status_search_and_bad_token(owner, paperless, monkeypatch):
    status = owner.get("/api/paperless/status").json()
    assert status["reachable"] is True and "token" not in json.dumps(status).lower()
    docs = owner.get("/api/paperless/documents", params={"q": "synthetic"}).json()
    assert docs["items"] == [{"id": 7, "title": "Synthetic Rechnung", "created": "2026-10-02", "url": "http://127.0.0.1:8010/documents/7/details"}]
    monkeypatch.setenv("PAPERLESS_TOKEN", "synthetic-wrong-token")
    assert owner.get("/api/paperless/status").json()["error"] == "Paperless rejected the token"
    assert owner.get("/api/paperless/documents", params={"q": "synthetic"}).status_code == 502


def test_receipt_is_sent_once(owner, paperless, upload_dir):
    receipt = owner.post("/api/receipts", files={"file": ("bon.png", PNG, "image/png")}).json()
    owner.patch(f"/api/receipts/{receipt['id']}", json={"merchant": "Synthetic Markt", "receipt_date": "2026-10-02"})
    sent = owner.post(f"/api/receipts/{receipt['id']}/paperless")
    assert sent.status_code == 200 and sent.json()["paperless_task"] == "synthetic-task-1" and sent.json()["paperless_sent_at"]
    posts = [r for r in paperless if r.method == "POST"]
    assert len(posts) == 1 and b"Kassenzettel Synthetic Markt 2026-10-02" in posts[0].content and PNG in posts[0].content
    again = owner.post(f"/api/receipts/{receipt['id']}/paperless").json()
    assert again["already_sent"] is True and len([r for r in paperless if r.method == "POST"]) == 1


def test_rejects_url_with_credentials(monkeypatch):
    monkeypatch.setenv("PAPERLESS_URL", "http://" + "synthetic" + ":" + "x" + "@" + "paperless.test")
    monkeypatch.setenv("PAPERLESS_TOKEN", "synthetic-paperless-token")
    assert pl.config() is None
