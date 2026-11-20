from datetime import date
import hashlib
from decimal import Decimal
from pathlib import PurePath
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import current_user
from .config import settings
from .db import get_db
from .finance import account_json, allocation_backing, bucket_json, contracts, funding_eligible, latest_balance, local_today, overview, serialize, ZERO
from .importer import ingest, parse_workbook
from .locking import lock_owner
from .models import Account, Allocation, AllocationEvent, Balance, Bucket, Finding, Import, Obligation, Setting, Transaction, TransactionRevision, User

router = APIRouter(tags=["finance"])


def owned(db, cls, ident, user):
    obj = db.scalar(select(cls).where(cls.id == ident, cls.user_id == user.id).execution_options(populate_existing=True))
    if obj is None:
        raise HTTPException(404, "Not found")
    return obj


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PriceBody(StrictBody):
    input: Decimal = Field(ge=0, max_digits=20, decimal_places=8)
    output: Decimal = Field(ge=0, max_digits=20, decimal_places=8)
    currency: Literal["EUR"] = "EUR"
    verified: bool = False


class AIPolicyBody(StrictBody):
    budget_currency: Literal["EUR"] = "EUR"
    enabled: bool = False
    external_consent: bool = False
    proactive_consent: bool = False
    model: str = Field(default="", max_length=160)
    prices: dict[str, PriceBody] = Field(default_factory=dict, max_length=20)
    total_limit: Decimal = Field(default=ZERO, ge=0, max_digits=20, decimal_places=8)
    monthly_limit: Decimal = Field(default=ZERO, ge=0, max_digits=20, decimal_places=8)
    channel_limits: dict[str, Decimal] = Field(default_factory=dict, max_length=4)
    run_limit: Decimal = Field(default=ZERO, ge=0, max_digits=20, decimal_places=8)
    max_concurrent: int = Field(default=1, ge=1, le=8)
    max_input_tokens: int = Field(default=4096, ge=128, le=32000)
    max_output_tokens: int = Field(default=512, ge=1, le=4096)
    max_tools: int = Field(default=3, ge=1, le=3)
    max_steps: int = Field(default=6, ge=3, le=8)
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class NotificationBody(StrictBody):
    enabled: bool = False
    server: str = Field(default="", max_length=500)
    topic: str = Field(default="", max_length=100)
    timezone: str = Field(default="Europe/Berlin", max_length=80)
    quiet_start: int = Field(default=1320, ge=0, lt=1440)
    quiet_end: int = Field(default=480, ge=0, lt=1440)
    stale_after_hours: int = Field(default=168, ge=1, le=8760)
    events: list[Literal["weekly", "monthly", "report_ready", "anomaly", "import_changed"]] = Field(default_factory=list)
    reminder_hour: int = Field(default=9, ge=0, le=23)
    reminder_minute: int = Field(default=0, ge=0, le=59)
    weekly_day: int = Field(default=0, ge=0, le=6)


@router.get("/overview")
def get_overview(start: date | None = None, end: date | None = None, db: Session = Depends(get_db), user=Depends(current_user)):
    if start and end and start > end:
        raise HTTPException(422, "Start must precede end")
    return overview(db, user.id, start, end)


@router.get("/accounts")
def accounts(db: Session = Depends(get_db), user=Depends(current_user)):
    return [account_json(db, a) for a in db.scalars(select(Account).where(Account.user_id == user.id).order_by(Account.name))]


class AccountPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    included: bool | None = None
    ownership: Literal["owned", "external", "unknown"] | None = None
    purpose: Literal["checking", "savings", "investment", "credit", "cash", "other"] | None = None
    inactive: bool | None = None
    owner_share: Decimal | None = Field(default=None, ge=0, le=100)


@router.patch("/accounts/{ident}")
def update_account(ident: str, body: AccountPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    account = owned(db, Account, ident, user)
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(account, key, value)
    db.commit()
    return account_json(db, account)


@router.get("/accounts/{ident}/balances")
def balances(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    owned(db, Account, ident, user)
    return serialize(list(db.scalars(select(Balance).where(Balance.account_id == ident).order_by(Balance.observed_date))))


@router.get("/transactions")
def transactions(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                 search: str | None = Query(None, max_length=300), start: date | None = None, end: date | None = None,
                 account_id: str | None = None, category: str | None = None, currency: str | None = None,
                 min_amount: Decimal | None = None, max_amount: Decimal | None = None,
                 merchant: str | None = None, is_transfer: bool | None = None, contract: str | None = None,
                 tag: str | None = None,
                 view: Literal["included_spending", "all_transactions", "owned_liquid"] | None = None,
                 db: Session = Depends(get_db), user=Depends(current_user)):
    query = select(Transaction).where(Transaction.user_id == user.id)
    if view is not None:
        # MCP evidence links must resolve to exactly the same canonical view.
        # The default explorer remains all transactions for backward compatibility.
        query = query.join(Account, Account.id == Transaction.account_id).where(Account.user_id == user.id)
        if currency:
            query = query.where(Account.currency == currency)
        if view != "all_transactions":
            query = query.where(Account.included.is_(True), Account.ownership != "external",
                                Transaction.is_transfer.is_(False), Transaction.split_role.notin_(["parent", "excluded"]))
        if view == "owned_liquid":
            query = query.where(Account.ownership == "owned", Account.purpose != "investment")
    if search:
        query = query.where(or_(Transaction.merchant.icontains(search, autoescape=True), Transaction.description.icontains(search, autoescape=True)))
    for value, predicate in [(start, Transaction.booking_date >= start if start else None),
                             (end, Transaction.booking_date <= end if end else None),
                             (account_id, Transaction.account_id == account_id),
                             (currency, Transaction.currency == currency),
                             (min_amount, Transaction.amount >= min_amount if min_amount is not None else None),
                             (max_amount, Transaction.amount <= max_amount if max_amount is not None else None),
                             (is_transfer, Transaction.is_transfer == is_transfer),
                             (contract, Transaction.contract_name == contract)]:
        if value is not None:
            query = query.where(predicate)
    if category:
        query = query.where(func.coalesce(Transaction.category_override, Transaction.rule_category, Transaction.category) == category)
    if merchant:
        query = query.where(Transaction.merchant.icontains(merchant, autoescape=True))
    # Portable precise JSON array filtering across SQLite/PostgreSQL.
    if tag:
        ids = [tx.id for tx in db.scalars(query) if tag in tx.tags]
        query = query.where(Transaction.id.in_(ids))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Transaction.booking_date.desc(), Transaction.id).offset((page - 1) * page_size).limit(page_size))
    items = []
    for row in rows:
        item = serialize(row)
        item.pop("source")
        item.pop("user_id")
        item["effective_category"] = row.effective_category
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/transactions/{ident}")
def transaction(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    tx = owned(db, Transaction, ident, user)
    return {**serialize(tx), "revisions": serialize(list(db.scalars(select(TransactionRevision).where(TransactionRevision.transaction_id == ident))))}


class TransactionPatch(StrictBody):
    category_override: str | None = Field(default=None, max_length=300)
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(default=None, max_length=50)


@router.patch("/transactions/{ident}")
def patch_transaction(ident: str, body: TransactionPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    tx = owned(db, Transaction, ident, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "tags" and (value is None or any(len(t) > 100 for t in value)):
            raise HTTPException(422, "Invalid tags")
        setattr(tx, key, value)
    db.commit()
    return serialize(tx)


@router.post("/transactions/{ident}/reset")
def reset_transaction(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    tx = owned(db, Transaction, ident, user)
    tx.category_override = None
    db.commit()
    return serialize(tx)


async def upload_bytes(file):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "Only XLSX workbooks are accepted")
    data = await file.read(settings.max_upload_bytes + 1)
    await file.close()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Upload exceeds limit")
    return data


@router.post("/imports/preview")
async def preview(file: UploadFile = File(...), user=Depends(current_user)):
    rows, headers, unknown, warnings = parse_workbook(await upload_bytes(file))
    return {"row_count": len(rows), "columns": headers, "unknown_columns": unknown,
            "warnings": warnings, "accounts": len({r["account_key"] for r in rows})}


STALE_IMPORT_MINUTES = 30


def expire_stale_imports(db, user_id):
    """A background import that never finished (process restart) must not look 'processing' forever."""
    from .models import now
    from datetime import timedelta
    cutoff = now() - timedelta(minutes=STALE_IMPORT_MINUTES)
    changed = False
    for record in db.scalars(select(Import).where(Import.user_id == user_id, Import.status == "processing")):
        created = record.created_at if record.created_at.tzinfo else record.created_at.replace(tzinfo=cutoff.tzinfo)
        if created < cutoff:
            record.status = "failed"
            record.summary = {"error": "Import interrupted", "retry": "Upload the file again; source uploads are not retained"}
            changed = True
    if changed:
        db.commit()


def run_background_import(bind, user_id, data, filename, full_snapshot):
    """Runs after the HTTP response, in its own session; the upload request never waits for the import."""
    digest = hashlib.sha256(data).hexdigest()
    with sessionmaker(bind=bind, expire_on_commit=False)() as session:
        try:
            user = session.get(User, user_id)
            ingest(session, user, data, filename, full_snapshot)
        except BaseException as exc:
            session.rollback()
            record = session.scalar(select(Import).where(Import.user_id == user_id, Import.sha256 == digest))
            if record is not None and record.status != "completed":
                unsafe = isinstance(exc, HTTPException)
                record.status = "failed"
                record.summary = {"error": "Invalid or unsafe workbook" if unsafe else "Import failed",
                                  "retry": "Re-upload corrected workbook; source uploads are not retained"}
                session.commit()
            if not isinstance(exc, Exception):
                raise


@router.post("/imports")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...), full_snapshot: bool = Form(False),
                 background: bool = Form(False), db: Session = Depends(get_db), user=Depends(current_user)):
    filename = PurePath(file.filename or "upload.xlsx").name[:255]
    data = await upload_bytes(file)
    if background:
        digest = hashlib.sha256(data).hexdigest()
        lock_owner(db, user.id)
        record = db.scalar(select(Import).where(Import.user_id == user.id, Import.sha256 == digest).execution_options(populate_existing=True))
        if record is None or record.status != "completed":
            if record is None:
                record = Import(user_id=user.id, filename=filename, sha256=digest, status="processing", row_count=0, summary={})
                db.add(record)
                db.commit()
                background_tasks.add_task(run_background_import, db.get_bind(), user.id, data, filename, full_snapshot)
            elif record.status == "failed":
                record.status, record.summary = "processing", {}
                db.commit()
                background_tasks.add_task(run_background_import, db.get_bind(), user.id, data, filename, full_snapshot)
            # status "processing": the same file is already being imported; report it instead of starting a second run
            from fastapi.responses import JSONResponse
            return JSONResponse({**serialize(record), "duplicate": False, "background": True}, status_code=202)
        db.rollback()  # an identical completed import is answered below without queueing anything
    try:
        record, duplicate = ingest(db, user, data, filename, full_snapshot)
    except HTTPException:
        db.rollback()
        digest = hashlib.sha256(data).hexdigest()
        record = db.scalar(select(Import).where(Import.user_id == user.id, Import.sha256 == digest))
        if not record:
            record = Import(user_id=user.id, filename=filename, sha256=digest, status="failed", row_count=0,
                            summary={"error": "Invalid or unsafe workbook", "retry": "Re-upload corrected workbook; source uploads are not retained"})
            db.add(record)
            db.commit()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Concurrent import; retry safely") from None
    if not duplicate:
        # Update freshness only for a successful changed import; no network call here.
        from .notifications import NotificationSettings, queue_notification
        preferences = db.get(NotificationSettings, user.id)
        if preferences:
            from .models import now
            preferences.last_import_at = now()
            if preferences.enabled and "import_changed" in preferences.events:
                queue_notification(db, user.id, "import_changed", "import:" + record.id)
            db.commit()
    return {**serialize(record), "duplicate": duplicate}


@router.get("/imports")
def imports(db: Session = Depends(get_db), user=Depends(current_user)):
    expire_stale_imports(db, user.id)
    return serialize(list(db.scalars(select(Import).where(Import.user_id == user.id).order_by(Import.created_at.desc()))))


@router.get("/imports/{ident}")
def get_import(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    expire_stale_imports(db, user.id)
    return serialize(owned(db, Import, ident, user))


class BucketBody(StrictBody):
    name: str = Field(min_length=1, max_length=300)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    kind: Literal["real", "virtual"] = "virtual"
    target: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    due_date: date | None = None


class BucketPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    kind: Literal["real", "virtual"] | None = None
    target: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)
    due_date: date | None = None


@router.get("/buckets")
def buckets(db: Session = Depends(get_db), user=Depends(current_user)):
    backing = allocation_backing(db, user.id)
    return [bucket_json(db, b, backing=backing) for b in db.scalars(select(Bucket).where(Bucket.user_id == user.id).order_by(Bucket.name))]


@router.post("/buckets", status_code=201)
def create_bucket(body: BucketBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    bucket = Bucket(user_id=user.id, **body.model_dump())
    db.add(bucket)
    db.commit()
    return bucket_json(db, bucket)


@router.patch("/buckets/{ident}")
def patch_bucket(ident: str, body: BucketPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    bucket = owned(db, Bucket, ident, user)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key in {"name", "kind"}:
            raise HTTPException(422, "Name and kind cannot be null")
        setattr(bucket, key, value)
    db.commit()
    return bucket_json(db, bucket)


@router.delete("/buckets/{ident}")
def delete_bucket(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    bucket = owned(db, Bucket, ident, user)
    db.execute(delete(Allocation).where(Allocation.bucket_id == ident))
    db.execute(delete(Obligation).where(Obligation.bucket_id == ident))
    db.delete(bucket)
    db.commit()
    return {"ok": True}


class AllocationBody(StrictBody):
    account_id: str
    amount: Decimal = Field(ge=0, max_digits=24, decimal_places=8)


class AllocationList(StrictBody):
    allocations: list[AllocationBody] = Field(max_length=100)


@router.put("/buckets/{ident}/allocations")
def put_allocations(ident: str, body: AllocationList, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    bucket = owned(db, Bucket, ident, user)
    if len({a.account_id for a in body.allocations}) != len(body.allocations):
        raise HTTPException(422, "Duplicate account allocation")
    for item in body.allocations:
        account = owned(db, Account, item.account_id, user)
        if account.currency != bucket.currency or not funding_eligible(account):
            raise HTTPException(422, "Allocation requires included, owned, same-currency account")
        balance = latest_balance(db, account.id, local_today(db, user.id))
        reserved = db.scalar(select(func.sum(Allocation.amount)).where(Allocation.account_id == account.id, Allocation.bucket_id != ident)) or ZERO
        if not balance or item.amount + reserved > max(ZERO, balance.amount):
            raise HTTPException(409, "Insufficient unallocated observed funds")
    db.execute(delete(Allocation).where(Allocation.bucket_id == ident))
    for item in body.allocations:
        db.add(Allocation(bucket_id=ident, **item.model_dump()))
        db.add(AllocationEvent(bucket_id=ident, bucket_name=bucket.name, user_id=user.id, **item.model_dump()))
    if not body.allocations:
        # An explicit release is history too: amount zero marks "nothing earmarked any more".
        db.add(AllocationEvent(bucket_id=ident, bucket_name=bucket.name, user_id=user.id, account_id="", amount=ZERO))
    db.commit()
    return bucket_json(db, bucket)


class ObligationBody(StrictBody):
    name: str = Field(min_length=1, max_length=300)
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    period: Literal["monthly", "quarterly", "yearly", "once"]
    due_date: date | None = None
    scheduled_contributions: Decimal = Field(default=ZERO, ge=0, max_digits=24, decimal_places=8)


@router.post("/buckets/{ident}/obligations", status_code=201)
def add_obligation(ident: str, body: ObligationBody, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    owned(db, Bucket, ident, user)
    item = Obligation(bucket_id=ident, **body.model_dump())
    db.add(item)
    db.commit()
    return serialize(item)


class ObligationPatch(StrictBody):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    period: Literal["monthly", "quarterly", "yearly", "once"] | None = None
    due_date: date | None = None
    scheduled_contributions: Decimal | None = Field(default=None, ge=0, max_digits=24, decimal_places=8)


@router.patch("/buckets/{ident}/obligations/{obligation_id}")
def patch_obligation(ident: str, obligation_id: str, body: ObligationPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    owned(db, Bucket, ident, user)
    item = db.scalar(select(Obligation).where(Obligation.id == obligation_id, Obligation.bucket_id == ident))
    if not item:
        raise HTTPException(404, "Not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None and key != "due_date":
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value)
    db.commit()
    return serialize(item)


@router.get("/buckets/{ident}/allocation-history")
def allocation_history(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    events = db.scalars(select(AllocationEvent).where(AllocationEvent.bucket_id == ident, AllocationEvent.user_id == user.id)
                        .order_by(AllocationEvent.recorded_at.desc()).limit(500))
    names = {a.id: a.name for a in db.scalars(select(Account).where(Account.user_id == user.id))}
    return [{**serialize(e), "account_name": names.get(e.account_id)} for e in events]


@router.get("/transactions/{ident}/revisions")
def transaction_revisions(ident: str, db: Session = Depends(get_db), user=Depends(current_user)):
    """Source revisions newest first, each with the columns that differ from the next newer version."""
    tx = owned(db, Transaction, ident, user)
    revisions = list(db.scalars(select(TransactionRevision).where(TransactionRevision.transaction_id == ident)
                                .order_by(TransactionRevision.created_at.desc())))
    newer = (tx.source or {}).get("columns", {})
    out = []
    for rev in revisions:
        older = (rev.source or {}).get("columns", {})
        diff = [{"column": k, "was": older.get(k), "now": newer.get(k)} for k in sorted(set(older) | set(newer)) if older.get(k) != newer.get(k)]
        out.append({"id": rev.id, "import_id": rev.import_id, "created_at": rev.created_at, "changes": diff})
        newer = older
    return serialize(out)


@router.delete("/buckets/{ident}/obligations/{obligation_id}")
def remove_obligation(ident: str, obligation_id: str, db: Session = Depends(get_db), user=Depends(current_user)):
    lock_owner(db, user.id)
    owned(db, Bucket, ident, user)
    item = db.scalar(select(Obligation).where(Obligation.id == obligation_id, Obligation.bucket_id == ident))
    if not item:
        raise HTTPException(404, "Not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.get("/contracts")
def get_contracts(db: Session = Depends(get_db), user=Depends(current_user)):
    return contracts(db, user.id)


@router.get("/findings")
def findings(db: Session = Depends(get_db), user=Depends(current_user)):
    return serialize(list(db.scalars(select(Finding).where(Finding.user_id == user.id).order_by(Finding.created_at.desc()))))


class FindingPatch(StrictBody):
    status: Literal["open", "acknowledged", "dismissed"]


@router.patch("/findings/{ident}")
def patch_finding(ident: str, body: FindingPatch, db: Session = Depends(get_db), user=Depends(current_user)):
    item = owned(db, Finding, ident, user)
    item.status = body.status
    db.commit()
    return serialize(item)


DEFAULT_SETTINGS = {"locale": "de", "timezone": "Europe/Berlin", "currency": "EUR", "ai_enabled": False,
                    "external_ai_consent": False, "proactive_reports": False, "notifications_enabled": False}
SECRET_KEYS = {"api_key", "token", "password", "secret", "authorization"}


def public_settings(value):
    if isinstance(value, dict):
        return {k: public_settings(v) for k, v in value.items()
                if k.lower() not in SECRET_KEYS and not k.lower().endswith(("_token", "_secret", "_password", "_api_key"))}
    if isinstance(value, list):
        return [public_settings(v) for v in value]
    return value


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user=Depends(current_user)):
    row = db.get(Setting, user.id)
    result = {**DEFAULT_SETTINGS, **(row.data if row else {})}
    from .ai import AIPolicy
    from .notifications import NotificationSettings
    policy = db.get(AIPolicy, user.id)
    notifications = db.get(NotificationSettings, user.id)
    if policy:
        result["ai"] = {k: serialize(getattr(policy, k)) for k in AIPolicyBody.model_fields}
        result.update(ai_enabled=policy.enabled, external_ai_consent=policy.external_consent, proactive_reports=policy.proactive_consent)
    if notifications:
        result["notifications"] = {k: getattr(notifications, k) for k in NotificationBody.model_fields}
        result["notifications_enabled"] = notifications.enabled
    return public_settings(result)


@router.patch("/settings")
def patch_settings(body: dict, db: Session = Depends(get_db), user=Depends(current_user)):
    if len(str(body)) > 20000:
        raise HTTPException(422, "Settings too large")
    if "timezone" in body:
        try:
            ZoneInfo(body["timezone"])
        except (ZoneInfoNotFoundError, TypeError):
            raise HTTPException(422, "Invalid timezone") from None
    if "locale" in body and body["locale"] not in {"de", "en"}:
        raise HTTPException(422, "Unsupported locale")
    if "currency" in body and (not isinstance(body["currency"], str) or len(body["currency"]) != 3 or not body["currency"].isupper()):
        raise HTTPException(422, "Invalid currency")
    from pydantic import ValidationError
    from .ai import AIPolicy
    from .notifications import NotificationSettings, validate, ntfy_url
    try:
        if "ai" in body:
            # A policy is replaced as one validated unit, not partially mutated.
            policy_body = AIPolicyBody.model_validate(body["ai"])
            policy_data = policy_body.model_dump(mode="json")
            if any(key not in {"chat", "weekly", "monthly", "changed_import"} or Decimal(value) < 0
                   for key, value in policy_data["channel_limits"].items()):
                raise ValueError("Invalid channels")
            policy = db.get(AIPolicy, user.id)
            if policy is None:
                policy = AIPolicy(owner_id=user.id)
                db.add(policy)
            elif policy.budget_currency != "EUR":
                raise ValueError("Legacy budget currency requires explicit reconciliation")
            for key, value in policy_data.items():
                setattr(policy, key, value if key in {"prices", "channel_limits"} else getattr(policy_body, key))
        if "notifications" in body:
            preferences = NotificationBody.model_validate(body["notifications"])
            notification_data = preferences.model_dump()
            item = db.get(NotificationSettings, user.id)
            if item is None:
                item = NotificationSettings(owner_id=user.id)
                db.add(item)
            for key, value in notification_data.items():
                setattr(item, key, value)
            validate(item)
            if item.enabled:
                ntfy_url(item)
            last_import = db.scalar(select(Import).where(Import.user_id == user.id, Import.status == "completed").order_by(Import.created_at.desc()).limit(1))
            item.last_import_at = last_import.created_at if last_import else None
        # Legacy convenience booleans configure only existing real policy rows.
        for input_key, cls, attr in [("ai_enabled", AIPolicy, "enabled"), ("external_ai_consent", AIPolicy, "external_consent"),
                                     ("proactive_reports", AIPolicy, "proactive_consent"), ("notifications_enabled", NotificationSettings, "enabled")]:
            if input_key in body:
                if type(body[input_key]) is not bool:
                    raise ValueError("Invalid boolean")
                item = db.get(cls, user.id)
                if item is None and body[input_key]:
                    raise ValueError("Configure integration first")
                if item:
                    setattr(item, attr, body[input_key])
    except (ValueError, TypeError, ValidationError):
        db.rollback()
        raise HTTPException(422, "Invalid integration settings") from None
    row = db.get(Setting, user.id)
    if row is None:
        row = Setting(user_id=user.id, data={})
        db.add(row)
    row.data = {**row.data, **{k: v for k, v in body.items() if k not in {"ai", "notifications"}}}
    db.commit()
    return get_settings(db, user)
