"""Synthetic-only regressions for central source review findings 2–6."""
import io
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from sqlalchemy import event, select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.finance import bucket_json
from app.db import Base
from app.importer import parse_workbook
from app.models import Bucket, Transaction, User
from conftest import booking, upload


def month(client):
    return client.get("/api/overview", params={"start": "2026-01-01", "end": "2026-01-31"}).json()


def funded_bucket(owner, amount="500", target="800"):
    assert upload(owner, [booking(day="2026-01-01", **{"Kontostand": amount})]).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    assert owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"}).status_code == 200
    bucket = owner.post("/api/buckets", json={"name": "Synthetic reserve", "target": target}).json()
    assert owner.put(f"/api/buckets/{bucket['id']}/allocations", json={"allocations": [{"account_id": account["id"], "amount": amount}]}).status_code == 200
    return account, bucket


def test_removed_split_links_restore_unchanged_parent_and_source_transfer_flags(owner, db):
    parent = booking("parent", "-100", **{"Kategorie": "Parent"})
    children = [booking("first", "-60", **{"Parent ID": "parent", "Kategorie": "First"}),
                booking("second", "-40", **{"Parent ID": "parent", "Kategorie": "Second"})]
    assert upload(owner, [parent, *children]).status_code == 200
    assert month(owner)["currencies"][0]["expenses"] == "100"
    for child in children:
        child["Parent ID"] = None
    result = upload(owner, children)
    assert result.status_code == 200
    assert result.json()["summary"]["changed"] == 2
    assert all(t.split_role == "none" for t in db.scalars(select(Transaction)))
    for repeat in [children, [parent], [children[0]]]:
        assert upload(owner, repeat).status_code == 200
        overview = month(owner)
        assert overview["currencies"][0]["expenses"] == "200"
        assert {item["category"]: item["amount"] for item in overview["categories"]} == {"Parent": "100", "First": "60", "Second": "40"}


def test_removed_transfer_split_link_clears_inherited_transfer_status(owner, db):
    parent = booking("parent", "-100", **{"Umbuchung": "Ja"})
    children = [booking("first", "-60", **{"Parent ID": "parent"}), booking("second", "-40", **{"Parent ID": "parent"})]
    assert upload(owner, [parent, *children]).status_code == 200
    assert month(owner)["currencies"][0]["expenses"] == "0"
    for child in children:
        child["Parent ID"] = None
    assert upload(owner, children).status_code == 200
    assert month(owner)["currencies"][0]["expenses"] == "100"
    rows = list(db.scalars(select(Transaction)))
    assert sum(t.is_transfer for t in rows) == 1
    assert all(t.split_role == "none" for t in rows)


@pytest.mark.parametrize("scheduled", ["400", "600"])
def test_scheduled_contributions_cover_own_debit_before_shared_funds(owner, scheduled):
    _, bucket = funded_bucket(owner)
    for name, contribution in [("first", scheduled), ("second", "0")]:
        assert owner.post(f"/api/buckets/{bucket['id']}/obligations", json={"name": name, "amount": "400", "period": "once",
                          "scheduled_contributions": contribution, "due_date": "2026-02-01" if name == "first" else "2026-03-01"}).status_code == 201
    result = owner.get("/api/buckets").json()[0]
    assert result["funded"] == "500"
    assert result["required_monthly_contribution"] == "0"


def test_scheduled_excess_is_not_shared_and_effective_due_dates_determine_order(owner, db):
    _, bucket = funded_bucket(owner, amount="500")
    assert owner.patch(f"/api/buckets/{bucket['id']}", json={"due_date": "2026-03-01"}).status_code == 200
    # Null obligation date inherits March, not SQL NULLS FIRST. February consumes
    # 400 first, leaving a March shortfall of 400 / two remaining periods = 200.
    for body in [{"name": "inherited", "amount": "500", "period": "yearly"},
                 {"name": "explicit", "amount": "400", "period": "quarterly", "due_date": "2026-02-01"},
                 {"name": "scheduled excess", "amount": "200", "period": "once", "due_date": "2026-01-15", "scheduled_contributions": "1000"}]:
        assert owner.post(f"/api/buckets/{bucket['id']}/obligations", json=body).status_code == 201
    model = db.get(Bucket, bucket["id"])
    result = bucket_json(db, model, today=date(2026, 1, 1))
    assert result["required_monthly_contribution"] == "200"
    assert [o["name"] for o in result["obligations"]] == ["scheduled excess", "explicit", "inherited"]
    assert Decimal(result["monthly_obligation"]) == Decimal("2100") / 12  # 500 yearly + 400 quarterly


@pytest.mark.parametrize("account_patch,balance,backed,liquidity,status", [
    ({}, "100", "100", "0", "partial"),
    ({"included": False}, None, "0", "0", "ineligible"),
    ({"ownership": "external"}, None, "0", "0", "ineligible"),
    ({"ownership": "unknown"}, None, "0", "0", "ineligible"),
    ({"purpose": "investment"}, None, "0", "0", "ineligible"),
    ({}, "-100", "0", "-100", "unbacked"),
])
def test_backed_funds_follow_balance_and_account_eligibility(owner, account_patch, balance, backed, liquidity, status):
    account, bucket = funded_bucket(owner, target="500")
    if account_patch:
        assert owner.patch(f"/api/accounts/{account['id']}", json=account_patch).status_code == 200
    if balance:
        assert upload(owner, [booking(day="2026-01-01", **{"Kontostand": balance})]).status_code == 200
    result = owner.get("/api/buckets").json()[0]
    assert result["nominal_allocated"] == "500"
    assert result["funded"] == backed
    assert Decimal(result["funding_shortfall"]) == Decimal("500") - Decimal(backed)
    assert result["required_monthly_contribution"] == result["funding_shortfall"]
    assert result["allocations"][0]["funding_status"] == status
    assert result["warnings"]
    overview = owner.get("/api/overview").json()
    eur = next(c for c in overview["currencies"] if c["currency"] == "EUR")
    assert eur["allocated"] == backed
    assert eur["nominal_allocated"] == "500"
    assert eur["funding_shortfall"] == result["funding_shortfall"]
    assert eur["available_liquidity"] == liquidity
    assert set(result["warnings"]) <= set(overview["warnings"])


def test_competing_buckets_share_reduced_backing_once_in_stable_uuid_order(owner):
    account, first = funded_bucket(owner, amount="500", target="300")
    # Replace the first intent with 250, then reserve the other 250 in a second bucket.
    allocation = {"allocations": [{"account_id": account["id"], "amount": "250"}]}
    assert owner.put(f"/api/buckets/{first['id']}/allocations", json=allocation).status_code == 200
    second = owner.post("/api/buckets", json={"name": "Other reserve", "target": "300"}).json()
    assert owner.put(f"/api/buckets/{second['id']}/allocations", json=allocation).status_code == 200
    assert upload(owner, [booking(day="2026-01-01", **{"Kontostand": "300"})]).status_code == 200
    results = sorted(owner.get("/api/buckets").json(), key=lambda b: b["id"])
    assert [b["funded"] for b in results] == ["250", "50"]
    assert [b["required_monthly_contribution"] for b in results] == ["50", "250"]
    assert [b["funded"] for b in sorted(owner.get("/api/buckets").json(), key=lambda b: b["id"])] == ["250", "50"]
    overview = owner.get("/api/overview").json()["currencies"][0]
    assert overview["allocated"] == "300"
    assert overview["nominal_allocated"] == "500"
    assert overview["funding_shortfall"] == "200"
    assert overview["available_liquidity"] == "0"


def test_shared_ingest_acquires_owner_lock_before_financial_reads(owner, db):
    from app.importer import ingest
    from conftest import xlsx
    user = db.scalar(select(User))
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().lower())
    event.listen(db.get_bind(), "before_cursor_execute", record)
    try:
        ingest(db, user, xlsx([booking()]), "synthetic.xlsx")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", record)
    lock_index = next(i for i, sql in enumerate(statements) if sql.startswith("update users"))
    first_financial_read = next(i for i, sql in enumerate(statements) if sql.startswith("select") and any(f"from {name}" in sql for name in ("imports", "transactions", "accounts")))
    assert lock_index < first_financial_read


def test_shared_ingest_refreshes_cached_revisions_and_missing_flags_across_sessions(tmp_path):
    from app.importer import ingest
    from conftest import xlsx
    engine = create_engine("sqlite:///" + str(tmp_path / "synthetic-locking.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as http_session, factory() as watched_session:
        user = User(email="synthetic-locking@test.invalid", password_hash="not-used")
        http_session.add(user)
        http_session.commit()
        ingest(http_session, user, xlsx([booking("first", "-100"), booking("second", "-10")]), "synthetic.xlsx")
        watched_user = watched_session.get(User, user.id)
        # Keep old ORM instances deliberately, as a long-lived worker might.
        stale = list(watched_session.scalars(select(Transaction)))
        watched_session.commit()
        ingest(http_session, user, xlsx([booking("first", "-200")]), "synthetic-new.xlsx", full_snapshot=True)
        ingest(watched_session, watched_user, xlsx([booking("first", "-300"), booking("second", "-10")]), "synthetic-watched.xlsx")
        from app.models import TransactionRevision
        first = watched_session.scalar(select(Transaction).where(Transaction.amount == Decimal("-300")))
        revisions = list(watched_session.scalars(select(TransactionRevision).where(TransactionRevision.transaction_id == first.id)))
        assert {r.source["columns"]["Betrag"] for r in revisions} == {"-100", "-200"}
        assert all(not row.missing_from_latest for row in watched_session.scalars(select(Transaction)))
        assert all(row.amount != Decimal("-100") for row in stale)
    engine.dispose()


@pytest.mark.parametrize("lexeme", ["123456789012345.67000000", "-9999999999999999.12345678", "0.12345678", "1.2345678E-1"])
@pytest.mark.parametrize("sheet_path", ["xl/worksheets/sheet1.xml", "xl/custom/data.xml"])
def test_numeric_source_lexemes_and_decimal_normalization_are_exact(lexeme, sheet_path):
    book = Workbook()
    book.active.append(["Buchungsdatum", "Konto-ID", "Betrag", "Kontostand", "Buchungs-ID", "Unknown numeric"])
    book.active.append(["2026-01-01", "synthetic", 1, 1, "synthetic-booking", 1])
    initial = io.BytesIO()
    book.save(initial)
    result = io.BytesIO()
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(initial) as source, ZipFile(result, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            filename = item.filename
            if item.filename == "xl/worksheets/sheet1.xml":
                root = ElementTree.fromstring(data)
                for cell in ("C2", "D2", "F2"):
                    root.find(f'.//s:c[@r="{cell}"]/s:v', ns).text = lexeme
                data = ElementTree.tostring(root)
                filename = sheet_path
            elif item.filename == "xl/_rels/workbook.xml.rels":
                root = ElementTree.fromstring(data)
                for relationship in root:
                    if relationship.get("Type", "").endswith("/worksheet"):
                        relationship.set("Target", "/" + sheet_path)
                data = ElementTree.tostring(root)
            target.writestr(filename, data)
    rows, *_ = parse_workbook(result.getvalue())
    assert rows[0]["amount"] == Decimal(lexeme)
    assert rows[0]["balance"] == Decimal(lexeme)
    assert rows[0]["source"]["columns"]["Betrag"] == lexeme
    assert rows[0]["source"]["columns"]["Kontostand"] == lexeme
    assert rows[0]["source"]["unknown"]["Unknown numeric"] == lexeme
