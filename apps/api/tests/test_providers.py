"""Provider detection from IBANs and the manual override and filter.

Synthetic account numbers are assembled at runtime so no IBAN-shaped literal is stored in the repository.
"""
from app.providers import from_iban, from_name
from conftest import booking, upload


def iban(country: str, check: str, body: str, sep: str = "") -> str:
    return country + check + sep + body


def test_from_iban_and_name():
    assert from_iban(iban("DE", "00", "1001 1001 0000 0000 00", " ")) == "N26"
    assert from_iban(iban("DE", "00", "12030000" + "0" * 10)) == "DKB"
    assert from_iban(iban("DE", "00", "67050000" + "0" * 10)) == "Sparkasse"
    assert from_iban(iban("DE", "00", "66090000" + "0" * 10)) == "Volksbank / Raiffeisenbank"
    assert from_iban(iban("NL", "00", "BUNQ" + "0" * 10)) == "bunq"
    assert from_iban("synthetic-account") is None and from_iban(None) is None
    assert from_name("someone@example.test") == "PayPal" and from_name("Girokonto") is None


def test_detected_on_import_manual_override_and_filter(owner):
    rows = [booking("a", "-10", **{"Konto-ID": iban("DE", "00", "12030000" + "0" * 9 + "1"), "Konto": "Synthetic DKB"}),
            booking("b", "-20", **{"Konto-ID": "synthetic-unknown", "Konto": "Synthetic other"})]
    assert upload(owner, rows).status_code == 200
    accounts = {a["name"]: a for a in owner.get("/api/accounts").json()}
    assert accounts["Synthetic DKB"]["provider"] == "DKB" and accounts["Synthetic DKB"]["provider_source"] == "detected"
    other = accounts["Synthetic other"]
    assert other["provider"] is None and other["provider_source"] == "unknown"
    patched = owner.patch(f"/api/accounts/{other['id']}", json={"provider": "bunq"}).json()
    assert patched["provider"] == "bunq" and patched["provider_source"] == "manual"
    assert "bunq" in owner.get("/api/account-providers").json()["used"]
    listed = owner.get("/api/transactions", params={"provider": "bunq"}).json()["items"]
    assert [float(t["amount"]) for t in listed] == [-20.0]
    cleared = owner.patch(f"/api/accounts/{other['id']}", json={"provider": ""}).json()
    assert cleared["provider"] is None
