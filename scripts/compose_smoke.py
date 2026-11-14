"""Synthetic-only deployed API smoke and backup/restore verification.

Requires openpyxl. Never point this at an installation containing real data.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import io
import json
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--base-url", default="http://localhost:8080/api")
    args = parser.parse_args()
    config = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines() if line and not line.startswith("#") and "=" in line)
    bootstrap = os.getenv("FINSIGHT_BOOTSTRAP_SECRET", config.get("FINSIGHT_BOOTSTRAP_SECRET", ""))
    if not bootstrap:
        raise SystemExit("Bootstrap configuration required for isolated smoke test")
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ""
    public = urlsplit(args.base_url)
    origin = f"{public.scheme}://{public.netloc}"

    def request(path: str, method: str = "GET", payload=None, raw=None, content_type=None):
        headers = {"Origin": origin}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if payload is not None:
            raw = json.dumps(payload).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        try:
            with opener.open(Request(args.base_url + path, data=raw, headers=headers, method=method), timeout=90) as response:
                return json.load(response)
        except HTTPError as exc:
            # Do not print server bodies or potentially sensitive values.
            raise RuntimeError(f"Smoke request failed: {method} {path.split('?')[0]} HTTP {exc.code}") from None

    def wait_for_health(timeout=90.0, interval=2.0):
        import time
        deadline = time.monotonic() + timeout
        while True:
            try:
                with opener.open(Request(args.base_url + "/health", headers={"Origin": origin}), timeout=10) as response:
                    if json.load(response).get("status") == "ok":
                        return
            except (HTTPError, OSError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("Service did not become healthy in time")
            time.sleep(interval)

    wait_for_health()
    credentials = {"email": "smoke@example.invalid", "password": hashlib.sha256((bootstrap + "synthetic-smoke").encode()).hexdigest()}
    try:
        opener.open(Request(args.base_url + "/auth/login", data=json.dumps(credentials).encode(),
                            headers={"Origin": "https://attacker.example.invalid", "Content-Type": "application/json"},
                            method="POST"), timeout=15)
    except HTTPError as exc:
        assert exc.code == 403, "Untrusted browser origin must be rejected"
    else:
        raise AssertionError("Untrusted origin was accepted")
    status = request("/auth/status")
    if not status["initialized"]:
        if args.verify_only:
            raise AssertionError("Restored owner missing")
        auth = request("/auth/setup", "POST", {**credentials, "bootstrap_secret": bootstrap})
    else:
        auth = request("/auth/login", "POST", credentials)
    csrf = auth["csrf_token"]
    if not args.verify_only:
        from openpyxl import Workbook
        headers = ["Buchungstag", "Referenzkonto", "Name Referenzkonto", "Betrag", "Kontostand", "Waehrung", "Beguenstigter/Auftraggeber", "IBAN Beguenstigter/Auftraggeber", "Verwendungszweck", "E-Ref", "Mandatsreferenz", "Glaeubiger-ID", "Analyse-Hauptkategorie", "Analyse-Unterkategorie", "Analyse-Vertrag", "Analyse-Vertragsturnus", "Analyse-Vertrags-ID", "Analyse-Umbuchung", "Analyse-Vom frei verfuegbaren Einkommen ausgeschlossen", "Analyse-Umsatzart", "Analyse-Betrag", "Analyse-Woche", "Analyse-Monat", "Analyse-Quartal", "Analyse-Jahr", "Buchungs-ID", "Referenz-Original-ID", "Split-Typ", "Tags"]
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(headers)
        for identifier, account, amount, balance, transfer in [
            ("synthetic-income", "TEST-CHECKING", 2000, 2000, False),
            ("synthetic-transfer-out", "TEST-CHECKING", -60, 1940, True),
            ("synthetic-transfer-in", "TEST-SAVINGS", 60, 60, True),
            ("synthetic-insurance", "TEST-CHECKING", -720, 1220, False),
        ]:
            row = {"Buchungstag": datetime(2025, 10, 1 + len(list(sheet.rows)) - 1), "Referenzkonto": account,
                   "Name Referenzkonto": account, "Betrag": amount, "Kontostand": balance, "Waehrung": "EUR",
                   "Buchungs-ID": identifier, "Analyse-Umbuchung": "ja" if transfer else "nein",
                   "Analyse-Vertrag": "nein", "Analyse-Hauptkategorie": "Synthetic", "Beguenstigter/Auftraggeber": "Synthetic provider"}
            sheet.append([row.get(key) for key in headers])
        output = io.BytesIO()
        workbook.save(output)
        boundary = "FinSightSyntheticBoundary"
        raw = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.xlsx\"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n".encode() + output.getvalue() + f"\r\n--{boundary}--\r\n".encode())
        media = f"multipart/form-data; boundary={boundary}"
        assert request("/imports/preview", "POST", raw=raw, content_type=media)["row_count"] == 4
        request("/imports", "POST", raw=raw, content_type=media)
        assert request("/imports", "POST", raw=raw, content_type=media)["duplicate"]
    transactions = request("/transactions")
    assert transactions["total"] == 4
    accounts = request("/accounts")
    assert len(accounts) == 2
    overview = request("/overview?start=2025-10-01&end=2025-10-31")
    eur = next(item for item in overview["currencies"] if item["currency"] == "EUR")
    assert Decimal(eur["income"]) == Decimal("2000")
    assert Decimal(eur["expenses"]) == Decimal("720")
    assert Decimal(eur["surplus"]) == Decimal("1280")
    print("Synthetic deployment checks passed: auth, import, idempotency, transfers, currency totals, restoration invariants.")


if __name__ == "__main__":
    main()
