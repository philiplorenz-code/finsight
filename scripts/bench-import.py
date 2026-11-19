"""Import benchmark with synthetic, realistic-shaped data (60 accounts, 29 columns), profiled with cProfile.

Usage: cd apps/api && .venv/bin/python ../../scripts/bench-import.py [rows]
No real data is read; runs on in-memory SQLite, so it measures parsing and Python-side work only.
"""
import cProfile, io, pstats, random, sys, time
from datetime import date, timedelta
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base
from app.models import User
from app.importer import ingest

N = int(sys.argv[1]) if len(sys.argv) > 1 else 13000
HEAD = ["Buchungs-ID", "Konto-ID", "Konto", "Buchungsdatum", "Wertstellung", "Betrag", "Währung", "Empfänger", "Verwendungszweck",
        "Kategorie", "Umbuchung", "Parent ID", "Split", "Vertrag", "Analyse-Vertrags-ID", "Analyse-Vertragsturnus", "Kontostand",
        "Hauptkategorie", "Unterkategorie", "Tags", "IBAN", "BIC", "Notiz", "Ort", "Land", "Mandatsreferenz", "Gläubiger-ID", "Kartennummer", "Quelle"]
random.seed(7)
def build(n, offset=0):
    wb = Workbook(); ws = wb.active; ws.append(HEAD)
    d0 = date(2023, 1, 1)
    for i in range(n):
        k = i + offset
        acct = k % 60
        ws.append([f"id-{k}", f"acc-{acct}", f"Konto {acct}", (d0 + timedelta(days=k % 1400)).isoformat(), None, f"{random.uniform(-200, 150):.2f}", "EUR",
                   f"Händler {k % 400}", f"Verwendungszweck Nummer {k} mit etwas längerem Text", "Sonstiges", "Nein", None, None, "nein" if k % 7 else "ja",
                   f"C{k % 83}" if k % 7 == 0 else None, "monatlich" if k % 7 == 0 else None, f"{random.uniform(0, 9000):.2f}",
                   "Haupt", "Unter", None, "DE00" + str(acct), "BIC", None, "Ort", "DE", None, None, None, "fg"])
    b = io.BytesIO(); wb.save(b); return b.getvalue()

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
S = sessionmaker(bind=engine, expire_on_commit=False)
with S() as db:
    user = User(email="b@x.invalid", password_hash="x"); db.add(user); db.commit()
    for label, data in (("first import", build(N)), ("re-import +5% new", build(int(N * 1.05)))):
        pr = cProfile.Profile(); t = time.time(); pr.enable()
        rec, dup = ingest(db, user, data, "bench.xlsx", True)
        pr.disable()
        print(f"{label}: {time.time()-t:.1f}s rows={rec.row_count} summary={ {k: rec.summary.get(k) for k in ('added','changed','unchanged','missing')} }")
        out = io.StringIO(); pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats(14); print("\n".join(out.getvalue().splitlines()[4:30]))
