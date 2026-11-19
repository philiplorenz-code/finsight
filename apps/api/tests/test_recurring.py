"""Synthetic-only recurring contract detection, classification, decisions and totals."""
from datetime import date, timedelta
from decimal import Decimal

from app.recurring import classify, infer_period, normalize_key
from conftest import booking, upload

D = Decimal


def series(payee, amount, start, months, step=1, category="Sonstiges", skip=(), prefix=None):
    rows = []
    for i in range(months):
        if i in skip:
            continue
        year, month = divmod(start.month - 1 + i * step, 12)
        day = date(start.year + year, month + 1, min(start.day, 28)).isoformat()
        rows.append(booking(f"{prefix or payee}-{i}", f"-{amount}", day=day, **{"Empfänger": payee, "Kategorie": category}))
    return rows


def items(owner):
    return {i["name"]: i for i in owner.get("/api/contracts").json()["items"]}


def test_period_inference_tolerates_a_missing_booking_and_rejects_one_offs():
    d = [date(2026, 1, 15) + timedelta(days=30 * i) for i in range(8)]
    amounts = [D(40)] * 8
    assert infer_period(d, amounts)[0] == "monthly"
    gap = d[:3] + d[4:]
    assert infer_period(gap, [D(40)] * len(gap))[0] == "monthly", "one missing month keeps the contract"
    assert infer_period([date(2026, 1, 1), date(2026, 1, 20), date(2026, 5, 3), date(2026, 5, 9)], [D(10)] * 4) is None
    assert infer_period(d, [D(10), D(80), D(15), D(200), D(12), D(90), D(10), D(70)]) is None, "unstable amounts"
    assert infer_period([date(2025, 3, 1), date(2026, 3, 2)], [D(120), D(120)])[0] == "yearly"
    assert infer_period([date(2026, 1, 5), date(2026, 7, 6), date(2027, 1, 4)], [D(300)] * 3)[0] == "half_yearly"
    q = [date(2026, 1, 1), date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]
    assert infer_period(q, [D(60)] * 4)[0] == "quarterly"


def test_classification_uses_category_and_keywords():
    assert classify("Allianz Lebensversicherung", None) == "insurance"
    assert classify("Hausverwaltung", "Miete") == "housing"
    assert classify("Autokredit Bank", "Kredit") == "loan"
    assert classify("Netflix International", None) == "subscription"
    assert classify("Stadtwerke Muster", "Strom") == "utility"
    assert classify("Irgendein Verein", "Sonstiges") == "other"
    assert normalize_key("Allianz Vers. 123456 / Police 7") == normalize_key("ALLIANZ vers. 99 police")


def test_detects_contracts_totals_candidates_and_stopped(owner):
    today = date.today()
    start = date(today.year - 1, today.month, 5)
    rows = (series("Haftpflicht Muster Versicherung", 12, start, 12, category="Versicherung")
            + series("Netflix International", 13, start, 12, skip=(4,))
            + series("Hausverwaltung Beispiel", 900, start, 12, category="Miete")
            + series("Kfz Versicherung Beispiel", 480, start, 3, step=6, category="Versicherung")
            + series("Altes Fitness Studio", 30, date(today.year - 2, today.month, 5), 10, category="Sport")
            + [booking("once", "-250", day=start.isoformat(), **{"Empfänger": "Einmal Laden"})])
    assert upload(owner, rows).status_code == 200
    data = owner.get("/api/contracts").json()
    found = {i["name"]: i for i in data["items"]}
    assert found["Haftpflicht Muster Versicherung"]["kind"] == "insurance" and found["Haftpflicht Muster Versicherung"]["period"] == "monthly"
    assert found["Netflix International"]["kind"] == "subscription", "a skipped month does not lose the contract"
    assert found["Hausverwaltung Beispiel"]["kind"] == "housing"
    assert found["Kfz Versicherung Beispiel"]["period"] == "half_yearly" and D(found["Kfz Versicherung Beispiel"]["annual_cost"]) == 960
    assert "Einmal Laden" not in found
    assert found["Altes Fitness Studio"]["status"] == "stopped"
    eur = data["totals"]["EUR"]
    assert D(eur["by_kind"]["insurance"]["yearly"]) == D(12) * 12 + 960
    assert "Altes Fitness Studio" not in {c["name"] for c in data["cancellation_candidates"]}, "stopped contracts are not counted"
    assert D(eur["yearly"]) == D(144) + D(156) + D(10800) + D(960)
    names = [c["name"] for c in data["cancellation_candidates"]]
    assert names[0] == "Kfz Versicherung Beispiel" and "Hausverwaltung Beispiel" not in names, "rent is not a cancellation candidate"


def test_decisions_survive_reimport_and_can_rename_reclassify(owner):
    today = date.today()
    start = date(today.year - 1, today.month, 5)
    assert upload(owner, series("Mystery Abbuchung", 20, start, 10, prefix="a")).status_code == 200
    item = items(owner)["Mystery Abbuchung"]
    assert item["kind"] == "other" and item["decision"] is None
    key = item["key"]
    assert owner.put("/api/contracts/decision", json={"key": key, "decision": "confirm", "name": "Handyvertrag", "kind": "utility"}).status_code == 200
    again = items(owner)["Handyvertrag"]
    assert again["decision"] == "confirmed" and again["kind"] == "utility"
    more = series("Mystery Abbuchung", 20, start, 12, prefix="a")
    assert upload(owner, more).status_code == 200
    assert "Handyvertrag" in items(owner), "confirmation and rename survive a re-import of a newer export"
    assert owner.put("/api/contracts/decision", json={"key": key, "decision": "dismiss"}).status_code == 200
    data = owner.get("/api/contracts").json()
    assert "Handyvertrag" not in {i["name"] for i in data["items"]} and [d["key"] for d in data["dismissed"]] == [key]
    assert D(data["totals"].get("EUR", {"monthly": 0})["monthly"]) == 0, "dismissed contracts are not counted"
    assert owner.put("/api/contracts/decision", json={"key": key, "decision": "reset"}).status_code == 200
    assert "Mystery Abbuchung" in items(owner)
    assert owner.put("/api/contracts/decision", json={"key": key, "decision": "bogus"}).status_code == 422
    assert owner.put("/api/contracts/decision", json={"key": key, "decision": "confirm", "kind": "nope"}).status_code == 422
