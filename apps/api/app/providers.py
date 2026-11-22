"""Bank/provider of an account, derived from its IBAN or name. The account IBAN itself is stored for display (owner request).

German IBANs carry the bank code (BLZ) in positions 5-12; a few direct banks are matched exactly, the
large groups by the BLZ's fourth digit (5 = Sparkassen, 9 = Volks- und Raiffeisenbanken, 4 = Commerzbank).
Foreign IBANs carry a bank identifier (e.g. NL..BUNQ). Unknown codes give None, so the owner can set it.
"""
from __future__ import annotations

import re

from sqlalchemy import select

EXACT_BLZ = {
    "10011001": "N26", "12030000": "DKB", "50010517": "ING", "76030080": "Consorsbank",
    "20041111": "comdirect", "20041133": "comdirect", "20041144": "comdirect", "20041155": "comdirect",
    "10010010": "Postbank", "10070000": "Deutsche Bank", "10070024": "Deutsche Bank",
    "50070010": "Deutsche Bank", "50070024": "Deutsche Bank", "60050101": "BW-Bank",
    "70150000": "Stadtsparkasse München", "43060967": "GLS Bank", "30020900": "TARGOBANK",
}
BLZ_GROUP = {"5": "Sparkasse", "9": "Volksbank / Raiffeisenbank", "4": "Commerzbank"}
FOREIGN = (("NL", "BUNQ", "bunq"), ("NL", "INGB", "ING"), ("LT", "3250", "Revolut"), ("GB", "REVO", "Revolut"),
           ("IE", "REVO", "Revolut"), ("BE", "", None))
KNOWN = sorted({*EXACT_BLZ.values(), *BLZ_GROUP.values(), "bunq", "Revolut", "PayPal", "Trade Republic",
                "Scalable Capital", "C24", "Tomorrow", "Vivid", "Barclays", "Amex", "Bargeld"}, key=str.casefold)


def from_iban(value: str | None) -> str | None:
    iban = re.sub(r"\s", "", str(value or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", iban):
        return None
    country, rest = iban[:2], iban[4:]
    if country == "DE" and len(rest) >= 8 and rest[:8].isdigit():
        blz = rest[:8]
        return EXACT_BLZ.get(blz) or BLZ_GROUP.get(blz[3])
    for code, prefix, name in FOREIGN:
        if country == code and prefix and rest.startswith(prefix):
            return name
    return None


def from_name(name: str | None) -> str | None:
    text = (name or "").casefold()
    if "paypal" in text or re.search(r"[^\s@]+@[^\s@]+\.[a-z]{2,}", text):
        return "PayPal"
    return None


IBAN_COLUMNS = ("Referenzkonto", "IBAN", "Konto-ID", "Konto ID", "Kontonummer", "Account ID")


def iban_from_source(source) -> str | None:
    columns = (source or {}).get("columns") if isinstance(source, dict) else None
    if not isinstance(columns, dict):
        return None
    for key in IBAN_COLUMNS:
        if columns.get(key):
            return str(columns[key])
    return None


def clean_iban(value: str | None) -> str | None:
    iban = re.sub(r"\s", "", str(value or "")).upper()
    return iban if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban) else None


def backfill_ibans(db, user_id: str) -> int:
    """IBAN of accounts never checked, taken from one of their bookings (the export's Referenzkonto)."""
    from .models import Account, Transaction
    found = 0
    for account in db.scalars(select(Account).where(Account.user_id == user_id, Account.iban.is_(None))):
        tx = db.scalar(select(Transaction).where(Transaction.account_id == account.id).limit(1))
        account.iban = clean_iban(iban_from_source(tx.source if tx else None)) or ""
        found += bool(account.iban)
    return found


def detect_missing(db, user_id: str) -> int:
    """Fill the provider of accounts never checked before from one of their bookings. Returns how many were set."""
    from .models import Account, Transaction
    found = 0
    for account in db.scalars(select(Account).where(Account.user_id == user_id, Account.provider_source.is_(None))):
        tx = db.scalar(select(Transaction).where(Transaction.account_id == account.id).limit(1))
        provider = from_iban(iban_from_source(tx.source if tx else None)) or from_name(account.name)
        account.provider, account.provider_source = provider, ("detected" if provider else "unknown")
        found += bool(provider)
    return found
