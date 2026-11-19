import io
import re
import zipfile
from datetime import datetime

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
    book.properties.created = book.properties.modified = datetime(2026, 1, 1)
    raw = io.BytesIO()
    book.save(raw)
    # Zip entries carry the wall-clock time; pin it so identical rows always give identical bytes (and hash).
    stream = io.BytesIO()
    with zipfile.ZipFile(raw) as source, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0))
            clone.compress_type = zipfile.ZIP_DEFLATED
            content = source.read(info.filename)
            if info.filename == "docProps/core.xml":  # openpyxl stamps the save time into the properties
                content = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>2026-01-01T00:00:00Z", content)
            target.writestr(clone, content)
    return stream.getvalue()


def booking(ident="booking-1", amount="-12.50", day="2026-01-15", **extra):
    return {"Buchungs-ID": ident, "Konto-ID": "synthetic-account", "Konto": "Synthetic checking",
            "Buchungsdatum": day, "Betrag": amount, "Währung": "EUR", "Empfänger": "Synthetic shop",
            "Verwendungszweck": "Synthetic only", "Kategorie": "Food", "Umbuchung": "Nein", **extra}


@pytest.fixture
def db(request, tmp_path):
    if request.node.get_closest_marker("concurrent_db"):
        # StaticPool shares ONE sqlite connection, which is unsafe when tests deliberately run
        # requests in parallel threads. A file database gives each session its own connection.
        engine = create_engine(f"sqlite:///{tmp_path / 'concurrent.db'}", connect_args={"check_same_thread": False})
    else:
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
