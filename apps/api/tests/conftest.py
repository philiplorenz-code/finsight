import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import Base, get_db
from app.main import app


HEADERS = ["Buchungs-ID", "Konto-ID", "Konto", "Buchungsdatum", "Wertstellung", "Betrag", "Währung",
           "Empfänger", "Verwendungszweck", "Kategorie", "Umbuchung", "Parent ID", "Split", "Vertrag", "Kontostand", "Mystery"]


def xlsx(rows, headers=None):
    book = Workbook()
    sheet = book.active
    sheet.append(headers or HEADERS)
    for row in rows:
        if isinstance(row, dict):
            sheet.append([row.get(h) for h in (headers or HEADERS)])
        else:
            sheet.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def booking(ident="booking-1", amount="-12.50", day="2026-01-15", **extra):
    return {"Buchungs-ID": ident, "Konto-ID": "synthetic-account", "Konto": "Synthetic checking",
            "Buchungsdatum": day, "Betrag": amount, "Währung": "EUR", "Empfänger": "Synthetic shop",
            "Verwendungszweck": "Synthetic only", "Kategorie": "Food", "Umbuchung": "Nein", **extra}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db):
    settings.bootstrap_secret = "synthetic-bootstrap-secret"
    settings.cookie_secure = False
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def owner(client):
    response = client.post("/api/auth/setup", json={"bootstrap_secret": "synthetic-bootstrap-secret",
                                                   "email": "synthetic@example.test", "password": "synthetic-long-password"})
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def upload(client, rows, **kwargs):
    return client.post("/api/imports", files={"file": ("synthetic.xlsx", xlsx(rows))}, **kwargs)
