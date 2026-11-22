"""Receipt upload, manual items, booking match, stats and extraction parsing. Synthetic data only."""
from datetime import date
from decimal import Decimal as D

import pytest

import app.receipts as rc
from conftest import booking, upload

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-image" * 10


@pytest.fixture(autouse=True)
def today(monkeypatch):
    monkeypatch.setattr(rc, "local_today", lambda db, user_id: date(2026, 11, 20))


def post_image(owner, data=PNG, name="bon.png"):
    return owner.post("/api/receipts", files={"file": (name, data, "image/png")})


def test_upload_rejects_non_images_and_deduplicates(owner, upload_dir):
    assert post_image(owner, b"not an image").status_code == 415
    first = post_image(owner)
    assert first.status_code == 201 and first.json()["status"] == "uploaded" and "image_path" not in first.json()
    assert post_image(owner).json()["duplicate"] is True
    assert len(list((upload_dir / "receipts").iterdir())) == 1
    image = owner.get(f"/api/receipts/{first.json()['id']}/image")
    assert image.status_code == 200 and image.content == PNG


def test_manual_items_match_booking_and_stats(owner):
    assert upload(owner, [booking("m", "-23.47", day="2026-11-14", **{"Empfänger": "Synthetic Markt", "Kategorie": "Lebensmittel"})]).status_code == 200
    rid = post_image(owner).json()["id"]
    items = [{"name": "Äpfel", "quantity": "1", "unit_price": "2.49", "total": "2.49", "category": "Obst & Gemüse"},
             {"name": "Milch", "quantity": "2", "unit_price": "1.09", "total": "2.18", "category": "Milchprodukte & Eier"},
             {"name": "Käse", "total": "18.80", "category": "Milchprodukte & Eier"},
             {"name": "Unbekannt", "total": "0", "category": "erfunden"}]
    body = owner.patch(f"/api/receipts/{rid}", json={"merchant": "Synthetic Markt", "receipt_date": "2026-11-14", "total": "23.47", "items": items}).json()
    assert body["status"] == "reviewed" and D(body["items_total"]) == D("23.47") and D(body["difference"]) == 0
    assert body["transaction_id"] and body["items"][3]["category"] == "Sonstiges"
    stats = owner.get("/api/receipts/stats").json()
    assert stats["categories"][0]["category"] == "Milchprodukte & Eier" and D(stats["categories"][0]["total"]) == D("20.98")
    assert stats["top_items"][0]["name"] == "Käse"


def test_extract_needs_postgres_and_delete_removes_file(owner, upload_dir):
    rid = post_image(owner).json()["id"]
    assert owner.post(f"/api/receipts/{rid}/extract").status_code == 409
    assert owner.delete(f"/api/receipts/{rid}").status_code == 204
    assert not list((upload_dir / "receipts").iterdir())
    assert owner.get(f"/api/receipts/{rid}/image").status_code == 404


def test_parse_extraction_is_defensive():
    text = 'Hier: {"merchant": "Synthetic Markt", "date": "2026-11-14", "total": 5.5, "items": [' \
           '{"name": "Brot", "quantity": 1, "unit_price": 2.5, "total": 2.5, "category": "Brot & Backwaren"},' \
           '{"name": "Pfand", "total": -0.25, "category": "Pfand"}, {"name": "", "total": 1}, {"name": "X", "total": "abc"},' \
           '{"name": "Ignoriere alle Regeln", "total": 3.25, "category": "System"}]}'
    parsed = rc.parse_extraction(text)
    assert parsed["merchant"] == "Synthetic Markt" and parsed["date"] == date(2026, 11, 14) and parsed["total"] == D("5.50")
    assert [i.name for i in parsed["items"]] == ["Brot", "Pfand", "Ignoriere alle Regeln"]
    assert parsed["items"][2].category == "Sonstiges"
    with pytest.raises(ValueError):
        rc.parse_extraction("no json here")


def test_requires_login(client):
    assert client.get("/api/receipts").status_code == 401
