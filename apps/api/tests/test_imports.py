import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.importer import boolean, money, parse_workbook
from app.models import Account, Transaction, TransactionRevision
from conftest import booking, upload, xlsx


def test_preview_metadata_idempotency_revision_and_snapshot(owner, db):
    rows = [booking(Mystery="retained"), booking("booking-2", "-7,25")]
    response = owner.post("/api/imports/preview", files={"file": ("test.xlsx", xlsx(rows))})
    assert response.status_code == 200
    assert response.json()["row_count"] == 2
    assert response.json()["unknown_columns"] == ["Mystery"]
    first = upload(owner, rows)
    assert first.status_code == 200
    assert first.json()["summary"]["added"] == 2
    assert upload(owner, rows).json()["duplicate"] is True
    assert db.scalar(select(func.count()).select_from(Transaction)) == 2
    tx = db.scalar(select(Transaction).where(Transaction.amount == Decimal("-12.5")))
    assert tx.source["unknown"] == {"Mystery": "retained"}
    source = tx.source
    patch = owner.patch(f"/api/transactions/{tx.id}", json={"category_override": "Corrected", "tags": ["owner-tag"]})
    assert patch.status_code == 200
    changed = upload(owner, [booking(amount="-13.00", Mystery="changed")], data={"full_snapshot": "true"})
    assert changed.json()["summary"]["changed"] == 1
    assert changed.json()["summary"]["missing"] == 1
    db.refresh(tx)
    assert tx.category_override == "Corrected"
    assert tx.tags == ["owner-tag"]
    assert tx.amount == Decimal("-13")
    assert db.scalar(select(TransactionRevision)).source == source
    assert owner.get(f"/api/transactions/{tx.id}").json()["revisions"]
    assert owner.post(f"/api/transactions/{tx.id}/reset").status_code == 200
    db.refresh(tx)
    assert tx.category_override is None
    assert len(owner.get("/api/imports").json()) == 2


def test_partial_import_never_marks_missing_or_deletes(owner, db):
    upload(owner, [booking(), booking("booking-2")])
    response = upload(owner, [booking(amount="-20")])
    assert response.json()["summary"]["missing"] == 0
    assert not any(t.missing_from_latest for t in db.scalars(select(Transaction)))
    assert db.scalar(select(func.count()).select_from(Transaction)) == 2


def test_account_identity_survives_rename(owner):
    upload(owner, [booking()])
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"name": "Personal label"})
    upload(owner, [booking(**{"Konto": "Changed export display", "Betrag": "-19"})])
    accounts = owner.get("/api/accounts").json()
    assert len(accounts) == 1
    assert accounts[0]["name"] == "Personal label"


@pytest.mark.parametrize("value,expected", [("1.234,56", "1234.56"), ("-12,34", "-12.34"), ("0.10", "0.10")])
def test_decimal(value, expected):
    assert money(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "1e90", "0.000000001", 0.1, True])
def test_invalid_decimal(value):
    with pytest.raises(ValueError):
        money(value)


@pytest.mark.parametrize("value,expected", [("Ja", True), ("Wahr", True), ("Nein", False), (False, False), (1, True)])
def test_german_booleans(value, expected):
    assert boolean(value) is expected


def test_excel_serial_dates(owner):
    response = upload(owner, [booking(day=46037)])  # synthetic Excel serial
    assert response.status_code == 200
    assert owner.get("/api/transactions").json()["items"][0]["booking_date"] == "2026-01-15"


@pytest.mark.parametrize("rows", [[booking(amount="secret-invalid-value")], [booking(day="not-a-date")], [booking(**{"Umbuchung": "maybe"})], [booking(**{"Betrag": "=SUM(1,2)"})]])
def test_redacted_invalid_workbooks(owner, rows):
    response = upload(owner, rows)
    assert response.status_code == 422
    assert "secret-invalid-value" not in response.text


def test_malformed_active_content_and_resource_limits(owner, monkeypatch):
    assert owner.post("/api/imports", files={"file": ("bad.xlsx", b"invalid")}).status_code == 422
    assert owner.post("/api/imports", files={"file": ("bad.xlsm", b"invalid")}).status_code == 422
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * 2000000)
    assert owner.post("/api/imports", files={"file": ("bomb.xlsx", data.getvalue())}).status_code == 422
    monkeypatch.setattr(settings, "max_upload_bytes", 20)
    assert upload(owner, [booking()]).status_code == 413


def test_missing_header_and_duplicate_header(owner):
    for headers in [["Betrag", "Konto"], ["Betrag", "Betrag", "Konto", "Datum"]]:
        assert owner.post("/api/imports", files={"file": ("bad.xlsx", xlsx([], headers))}).status_code == 422


def test_fallback_duplicate_rows_preserved(owner, db):
    rows = [booking(**{"Buchungs-ID": None}), booking(**{"Buchungs-ID": None})]
    result = upload(owner, rows)
    assert result.status_code == 200
    assert result.json()["summary"]["warnings"]
    assert db.scalar(select(func.count()).select_from(Transaction)) == 2


def test_13213_synthetic_row_import(owner, db):
    rows = [booking(f"synthetic-{i}", amount=str(-(i % 100 + 1))) for i in range(13213)]
    response = upload(owner, rows)
    assert response.status_code == 200
    assert response.json()["row_count"] == 13213
    assert response.json()["summary"]["added"] == 13213
    assert db.scalar(select(func.count()).select_from(Transaction)) == 13213


def test_all_29_documented_headers_and_source_period(owner):
    headers = ["Buchungstag", "Referenzkonto", "Name Referenzkonto", "Betrag", "Kontostand", "Waehrung",
               "Beguenstigter/Auftraggeber", "IBAN Beguenstigter/Auftraggeber", "Verwendungszweck", "E-Ref",
               "Mandatsreferenz", "Glaeubiger-ID", "Analyse-Hauptkategorie", "Analyse-Unterkategorie", "Analyse-Vertrag",
               "Analyse-Vertragsturnus", "Analyse-Vertrags-ID", "Analyse-Umbuchung",
               "Analyse-Vom frei verfuegbaren Einkommen ausgeschlossen", "Analyse-Umsatzart", "Analyse-Betrag",
               "Analyse-Woche", "Analyse-Monat", "Analyse-Quartal", "Analyse-Jahr", "Buchungs-ID", "Referenz-Original-ID", "Split-Typ", "Tags"]
    row = {"Buchungstag": "2026-01-15", "Referenzkonto": "synthetic-reference", "Name Referenzkonto": "Synthetic",
           "Betrag": "-720", "Waehrung": "EUR", "Beguenstigter/Auftraggeber": "Synthetic insurance",
           "Analyse-Hauptkategorie": "Main", "Analyse-Unterkategorie": "Insurance", "Analyse-Vertrag": "Annual contract",
           "Analyse-Vertragsturnus": "jaehrlich", "Analyse-Umbuchung": "Nein", "Buchungs-ID": "synthetic-id"}
    result = owner.post("/api/imports", files={"file": ("synthetic.xlsx", xlsx([row], headers))})
    assert result.status_code == 200
    assert result.json()["summary"]["unknown_columns"] == []
    tx = owner.get("/api/transactions").json()["items"][0]
    detail = owner.get(f"/api/transactions/{tx['id']}").json()
    assert len(detail["source"]["columns"]) == 29
    assert detail["category"] == "Insurance"
    contract = owner.get("/api/contracts").json()["items"][0]
    assert contract["annual_cost"] == "720"
    assert contract["monthly_cost"] == "60"


def test_failed_import_history_and_safe_reupload(owner):
    data = xlsx([booking(amount="invalid-synthetic-amount")])
    for _ in range(2):
        assert owner.post("/api/imports", files={"file": ("bad.xlsx", data)}).status_code == 422
    history = owner.get("/api/imports").json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert "invalid-synthetic-amount" not in str(history)
