"""Bounded XLSX ingestion. Source cells are never evaluated or logged."""
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import date, datetime, timedelta
from decimal import Decimal

from defusedxml.ElementTree import iterparse
from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from sqlalchemy import select

from .config import settings
from .finance import local_today
from .locking import lock_owner
from .models import Account, Balance, Import, Transaction, TransactionRevision


# Aliases are explicit: unrecognized fields remain source metadata, never discarded.
ALIASES = {
    "booking_id": ["Buchungs-ID", "Buchungs ID", "Buchungsnummer", "Buchung ID", "Transaktions-ID", "Booking ID", "ID"],
    "account_id": ["Konto-ID", "Konto ID", "Account ID", "Kontonummer", "IBAN", "Referenzkonto"],
    "account": ["Konto", "Kontoname", "Account", "Konto Name", "Name Referenzkonto"],
    "date": ["Buchungsdatum", "Datum", "Booking date", "Buchungstag"],
    "value_date": ["Wertstellungsdatum", "Wertstellung", "Valutadatum", "Valuta"],
    "amount": ["Betrag", "Amount"],
    "currency": ["Währung", "Waehrung", "Currency"],
    "merchant": ["Empfänger", "Empfänger / Auftraggeber", "Auftraggeber / Empfänger", "Begünstigter / Zahlungspflichtiger", "Name", "Merchant", "Zahlungspartner", "Beguenstigter/Auftraggeber"],
    "description": ["Verwendungszweck", "Beschreibung", "Description", "Buchungstext"],
    "category": ["Kategorie", "Category", "Unterkategorie", "Analyse-Unterkategorie"],
    "main_category": ["Analyse-Hauptkategorie"],
    "transfer": ["Umbuchung", "Ist Umbuchung", "Interne Umbuchung", "Interner Transfer", "Transfer", "Analyse-Umbuchung"],
    "parent": ["Übergeordnete Buchung", "Ursprungsbuchung", "Split Parent ID", "Parent ID", "Hauptbuchungs-ID"],
    "split": ["Splitbuchung", "Aufgeteilt", "Split", "Ist Splitbuchung"],
    "contract": ["Vertrag", "Vertragsname", "Contract", "Vertrag Name", "Analyse-Vertrag"],
    "contract_period": ["Analyse-Vertragsturnus"],
    "contract_id": ["Analyse-Vertrags-ID"],
    "original_id": ["Referenz-Original-ID"],
    "split_type": ["Split-Typ"],
    "metadata": ["IBAN Beguenstigter/Auftraggeber", "E-Ref", "Mandatsreferenz", "Glaeubiger-ID",
                 "Analyse-Vom frei verfuegbaren Einkommen ausgeschlossen", "Analyse-Umsatzart", "Analyse-Betrag",
                 "Analyse-Woche", "Analyse-Monat", "Analyse-Quartal", "Analyse-Jahr"],
    "balance": ["Kontostand", "Saldo", "Kontosaldo", "Balance"],
    "balance_date": ["Kontostand Datum", "Saldo Datum", "Balance Date"],
    "tags": ["Tags", "Schlagwörter", "Labels"],
}


@lru_cache(maxsize=4096)
def _norm(text: str) -> str:
    return re.sub(r"[\s_\-:/]+", "", text.strip().casefold())


def norm(value):
    # Called once per column per row (over a million times for a 13k-row export) with only a few dozen
    # distinct header strings, so the result is cached.
    return _norm(str(value))


LOOKUP = {norm(alias): field for field, aliases in ALIASES.items() for alias in aliases}


def money(value):
    if isinstance(value, (float, bool)):
        raise ValueError("Money requires an exact decimal input")
    if value is None or str(value).strip() == "":
        raise ValueError("Missing amount")
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("€", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    result = Decimal(text)
    if not result.is_finite() or abs(result) >= Decimal("1e16") or result.as_tuple().exponent < -8:
        raise ValueError("Invalid amount")
    return result


def parse_date(value, epoch):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return from_excel(value, epoch).date()
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError("Invalid date")


def boolean(value):
    if value in (None, ""):
        return False
    token = str(value).strip().casefold()
    if token in {"true", "wahr", "ja", "yes", "1", "x"}:
        return True
    if token in {"false", "falsch", "nein", "no", "0"}:
        return False
    raise ValueError("Invalid boolean")


def primitive(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return str(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def source_classification(values):
    """Rebuild source-only inputs; never reuse a previously derived split role."""
    split_type = str(values.get("split_type") or "").strip().casefold()
    child_types = {"child", "teilbuchung", "split-child", "split_child", "kind"}
    parent = values.get("parent") or (values.get("original_id") if split_type in child_types else None)
    parent_key = digest(["source", str(parent)]) if parent is not None and str(parent).strip() else None
    transfer = boolean(values.get("transfer"))
    split = boolean(values.get("split")) or bool(split_type and split_type not in {"none", "keine", "normal", "0"})
    return {"is_transfer": transfer, "transfer_uncertain": transfer, "split_parent_key": parent_key,
            "split_role": "child" if parent_key else "uncertain" if split else "none"}


def safe_zip(data):
    if len(data) > settings.max_upload_bytes:
        raise ValueError("Upload too large")
    numeric_cells = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len({x.filename for x in infos}) != len(infos):
            raise ValueError("Duplicate archive entries")
        if len(infos) > 2000 or sum(x.file_size for x in infos) > settings.max_uncompressed_bytes:
            raise ValueError("Expanded workbook exceeds limit")
        if any(x.flag_bits & 1 or x.file_size > max(1024 * 1024, x.compress_size * 500) for x in infos):
            raise ValueError("Unsafe archive")
        if any(".." in x.filename.split("/") or x.filename.startswith("/") for x in infos):
            raise ValueError("Unsafe archive path")
        if any("vbaProject" in x.filename or x.filename.startswith("xl/externalLinks/") for x in infos):
            raise ValueError("Active workbook content rejected")
        # Parse with defusedxml before openpyxl; reject hidden or cached formulas anywhere.
        for info in infos:
            if info.filename.endswith(".xml"):
                lexemes = {}
                with archive.open(info) as stream:
                    current_cell = None
                    numeric = False
                    for event, element in iterparse(stream, events=("start", "end")):
                        tag = element.tag.rsplit("}", 1)[-1]
                        if event == "start":
                            if element.tag == "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c":
                                current_cell = element.get("r")
                                numeric = element.get("t", "n") == "n"
                            continue
                        if tag == "f":
                            raise ValueError("Formulas are not allowed")
                        if element.tag == "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v" and numeric and element.text is not None:
                            if not current_cell or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", current_cell) or current_cell in lexemes:
                                raise ValueError("Invalid cell coordinate")
                            # Preserve the original decimal spelling, including trailing
                            # zeroes/exponents. No float conversion in source or money.
                            lexemes[current_cell] = element.text
                        if tag == "c":
                            current_cell, numeric = None, False
                        element.clear()
                if lexemes:
                    numeric_cells[info.filename] = lexemes
    return numeric_cells


def parse_workbook(data):
    try:
        numeric_cells = safe_zip(data)
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        try:
            if len(workbook.sheetnames) != 1 or len(workbook.worksheets) != 1:
                raise ValueError("Exactly one worksheet required")
            sheet = workbook.worksheets[0]
            # ReadOnlyWorksheet retains the resolved relationship target (sheet
            # names/IDs need not correspond to sheet1.xml). openpyxl is pinned <4.
            lexemes = numeric_cells.get(sheet._worksheet_path, {})
            if sheet.max_column and sheet.max_column > 256:
                raise ValueError("Too many columns")
            # Dimensions supplied by spreadsheet producers can be wrong.
            sheet.reset_dimensions()
            rows = sheet.iter_rows()
            headers = [str(c.value).strip() if c.value is not None else "" for c in next(rows)]
            if not headers or len(headers) > 256 or any(not x for x in headers) or len(set(headers)) != len(headers):
                raise ValueError("Invalid or duplicate headers")
            mapped = {h: LOOKUP.get(norm(h)) for h in headers}
            fields = set(mapped.values())
            if not {"date", "amount"} <= fields or not ({"account", "account_id"} & fields):
                raise ValueError("Required columns missing")
            result, warnings = [], set()
            for row_number, cells in enumerate(rows, start=2):
                if row_number > settings.max_import_rows + 1:
                    raise ValueError("Too many records")
                if len(cells) > len(headers) and any(c.value is not None for c in cells[len(headers):]):
                    raise ValueError("Unexpected extra cells")
                raw = {h: lexemes.get(getattr(cells[i], "coordinate", None), primitive(cells[i].value))
                       if i < len(cells) else None for i, h in enumerate(headers)}
                if any(isinstance(value, str) and len(value) > 100000 for value in raw.values()):
                    raise ValueError("Cell content exceeds limit")
                if all(v is None or v == "" for v in raw.values()):
                    continue
                values = {mapped[h]: cells[i].value if i < len(cells) else None for i, h in enumerate(headers) if mapped[h]}
                for index, header in enumerate(headers):
                    field = mapped[header]
                    if field in {"amount", "balance"} and index < len(cells):
                        cell = cells[index]
                        if cell.value is not None and cell.data_type == "n" and getattr(cell, "coordinate", None) not in lexemes:
                            raise ValueError("Numeric money requires its original XML lexeme")
                    # Dates use openpyxl's epoch/style interpretation. Every other
                    # numeric normalized input uses the XML spelling, especially
                    # money and numeric source identifiers.
                    if field and field not in {"date", "value_date", "balance_date"}:
                        values[field] = raw[header]
                booking_date = parse_date(values.get("date"), workbook.epoch)
                if not booking_date:
                    raise ValueError("Missing booking date")
                currency = str(values.get("currency") or "EUR").strip().upper()
                if not re.fullmatch(r"[A-Z]{3}", currency):
                    raise ValueError("Invalid currency")
                account_identity = str(values.get("account_id") or values.get("account") or "").strip()
                if not account_identity:
                    raise ValueError("Missing account identity")
                if not values.get("account_id"):
                    warnings.add("Account identity uses source name fallback; renamed exports may require reconciliation")
                merchant = str(values.get("merchant") or "")
                description = str(values.get("description") or "")
                if (len(str(values.get("account") or "")) > 300 or len(str(values.get("category") or "")) > 300
                        or len(str(values.get("main_category") or "")) > 300 or len(str(values.get("contract") or "")) > 300
                        or len(merchant) > 16000 or len(description) > 16000):
                    raise ValueError("Normalized text exceeds limit")
                amount = money(values.get("amount"))
                source_id = values.get("booking_id")
                if source_id is None or str(source_id).strip() == "":
                    warnings.add("Missing booking IDs: conservative content identity used; identical rows are ambiguous")
                    key = digest([booking_date, amount, currency, merchant, description])
                else:
                    key = digest(["source", str(source_id)])
                classification = source_classification(values)
                split_type = str(values.get("split_type") or "").strip().casefold()
                if classification["split_role"] == "uncertain":
                    warnings.add("Split metadata present without proven child-parent mapping; reconciliation requires review")
                result.append({
                    "account_key": digest([account_identity, currency]),
                    "account_name": str(values.get("account") or "Imported account"),
                    "source_key": key, "booking_date": booking_date,
                    "value_date": parse_date(values.get("value_date"), workbook.epoch),
                    "amount": amount, "currency": currency, "merchant": merchant,
                    "description": description, "category": str(values.get("category") or values.get("main_category") or "Uncategorized"),
                    **classification,
                    "contract_name": str(values["contract"]).strip() if values.get("contract") else None,
                    "tags": [s.strip() for s in re.split(r"[,;]", str(values.get("tags") or "")) if s.strip()],
                    "source": {"columns": raw, "unknown": {h: raw[h] for h in headers if not mapped[h]},
                               "contract_period": primitive(values.get("contract_period")),
                               "contract_id": primitive(values.get("contract_id")), "split_type": split_type},
                    "balance": money(values["balance"]) if values.get("balance") not in (None, "") else None,
                    "balance_date": parse_date(values.get("balance_date"), workbook.epoch) or booking_date,
                })
            # Distinct occurrences remain separate for fallback-identical bookings.
            seen = Counter()
            for row in result:
                identity = (row["account_key"], row["source_key"])
                seen[identity] += 1
                if seen[identity] > 1:
                    warnings.add("Duplicate booking identities preserved with occurrence suffix; reconciliation uncertain")
                    row["source_key"] = digest([row["source_key"], seen[identity]])
            return result, headers, [h for h in headers if not mapped[h]], sorted(warnings)
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception:
        # Never include parser messages: they may contain source values.
        raise HTTPException(422, "Invalid or unsafe workbook; check headers, dates, amounts and resource limits") from None


TRANSACTION_FIELDS = ["source_key", "booking_date", "value_date", "amount", "currency", "merchant", "description", "category",
                      "is_transfer", "transfer_uncertain", "split_parent_key", "split_role", "contract_name", "tags", "source"]


def validate_split_graph(accounts, transactions, rows=()):
    """Only flat source split graphs are supported; reject before financial writes.

    Overlay incoming rows on all retained source records, including records absent
    from a partial/full snapshot. Derived roles/links are never validation inputs.
    Any node whose parent itself has a parent is unsupported. This also catches
    every cycle (including a self-loop) without recursive, order-dependent walks.
    """
    account_keys = {account.id: account.source_key for account in accounts.values()}
    parents = {}
    for tx in transactions.values():
        source_values = {LOOKUP.get(norm(header)): value for header, value in tx.source.get("columns", {}).items()}
        parents[(account_keys[tx.account_id], tx.source_key)] = source_classification(source_values)["split_parent_key"]
    for row in rows:
        source_values = {LOOKUP.get(norm(header)): value for header, value in row["source"]["columns"].items()}
        parents[(row["account_key"], row["source_key"])] = source_classification(source_values)["split_parent_key"]
    for (account_key, source_key), parent_key in parents.items():
        if parent_key is not None and (
            parent_key == source_key or parents.get((account_key, parent_key)) is not None
        ):
            raise HTTPException(422, "Unsupported nested, cyclic or self-referencing split relationships; import rejected")


def ingest(db, user, data, filename, full_snapshot=False):
    # This is the shared boundary for HTTP and watched-file imports. Workers
    # may already hold this owner row; reacquiring it in the same transaction is safe.
    lock_owner(db, user.id)
    file_hash = hashlib.sha256(data).hexdigest()
    existing_import = db.scalar(select(Import).where(Import.user_id == user.id, Import.sha256 == file_hash)
                                .execution_options(populate_existing=True))
    accounts = {a.source_key: a for a in db.scalars(select(Account).where(Account.user_id == user.id).execution_options(populate_existing=True))}
    txs = {(t.account_id, t.source_key): t for t in db.scalars(select(Transaction).where(Transaction.user_id == user.id).execution_options(populate_existing=True))}
    if existing_import and existing_import.status == "completed":
        # Old successful hashes must not bless an unsupported retained graph.
        validate_split_graph(accounts, txs)
        return existing_import, True
    rows, headers, unknown, warnings = parse_workbook(data)
    validate_split_graph(accounts, txs, rows)
    record = existing_import or Import(user_id=user.id, filename=filename, sha256=file_hash)
    record.status, record.row_count = "processing", len(rows)
    db.add(record)
    db.flush()
    added = changed = unchanged = 0
    touched, seen, balances = set(), set(), {}
    for row in rows:
        account = accounts.get(row["account_key"])
        if account is None:
            account = Account(user_id=user.id, source_key=row["account_key"], name=row["account_name"], currency=row["currency"])
            db.add(account)
            db.flush()
            accounts[account.source_key] = account
        touched.add(account.id)
        key = (account.id, row["source_key"])
        seen.add(key)
        tx = txs.get(key)
        values = {field: row[field] for field in TRANSACTION_FIELDS}
        if tx:
            if tx.source != row["source"]:
                db.add(TransactionRevision(transaction_id=tx.id, import_id=record.id, source=tx.source))
                for field, value in values.items():
                    if field != "tags":  # user tag corrections survive reimports
                        setattr(tx, field, value)
                tx.import_id = record.id
                changed += 1
            else:
                unchanged += 1
            tx.missing_from_latest = False
        else:
            tx = Transaction(user_id=user.id, account_id=account.id, import_id=record.id, **values)
            db.add(tx)
            txs[key] = tx
            added += 1
        if row["balance"] is not None:
            previous = balances.get((account.id, row["balance_date"]))
            if previous is not None and previous != row["balance"]:
                warnings.append("Multiple same-day balances: final source-row observation used; intraday ordering unverified")
            balances[(account.id, row["balance_date"])] = row["balance"]
    missing = 0
    if full_snapshot:
        for key, tx in txs.items():
            if key[0] in touched and key not in seen:
                tx.missing_from_latest = True
                missing += 1
        warnings.append("Missing records flagged only for accounts present in this explicitly declared full snapshot")
        confirmed_on = local_today(db, user.id)
        for account in accounts.values():
            if account.id in touched:
                account.confirmed_through = confirmed_on
    for (account_id, observed_date), amount in balances.items():
        db.add(Balance(account_id=account_id, import_id=record.id, observed_date=observed_date, amount=amount))
    db.flush()
    # Split parents count instead of children when reconciliation is uncertain.
    groups = defaultdict(list)
    for tx in txs.values():
        source_values = {LOOKUP.get(norm(header)): value for header, value in tx.source.get("columns", {}).items()}
        for field, value in source_classification(source_values).items():
            setattr(tx, field, value)
        if tx.split_parent_key:
            groups[(tx.account_id, tx.split_parent_key)].append(tx)
    for key, children in groups.items():
        parent = txs.get(key)
        if parent and all(c.currency == parent.currency for c in children) and sum((c.amount for c in children), Decimal(0)) == parent.amount:
            parent.split_role = "parent"
            for child in children:
                child.split_role = "child"
                if parent.is_transfer:
                    child.is_transfer = True
                    child.transfer_uncertain = parent.transfer_uncertain
        else:
            warnings.append("Split reconciliation uncertain; unmatched children excluded when parent exists")
            if parent:
                parent.split_role = "uncertain"
            for child in children:
                child.split_role = "excluded" if parent else "orphan"
    # Only explicit transfer flags establish transfer status, never amount coincidence alone.
    flagged = [t for t in txs.values() if t.is_transfer]
    transfer_index = defaultdict(list)
    for tx in flagged:
        transfer_index[(tx.currency, tx.amount, tx.booking_date)].append(tx)
    for tx in flagged:
        matches = [other for delta in range(-3, 4)
                   for other in transfer_index[(tx.currency, -tx.amount, tx.booking_date + timedelta(days=delta))]
                   if other.account_id != tx.account_id]
        tx.transfer_uncertain = len(matches) != 1
    if any(t.transfer_uncertain for t in flagged):
        warnings.append("One-sided or ambiguous transfers excluded from consumption; counterpart ownership unverified")
    from .transfers import detect_transfers
    detect_transfers(db, user.id)
    record.status = "completed"
    record.summary = {"added": added, "changed": changed, "unchanged": unchanged, "missing": missing,
                      "columns": headers, "unknown_columns": unknown, "warnings": sorted(set(warnings)), "full_snapshot": full_snapshot}
    db.commit()
    return record, False
