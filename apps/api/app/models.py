from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_slot: Mapped[int] = mapped_column(Integer, unique=True, default=1)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "source_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(300))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    ownership: Mapped[str] = mapped_column(String(20), default="unknown")
    purpose: Mapped[str] = mapped_column(String(80), default="checking")
    inactive: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_share: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal(100))
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # detected | manual | unknown
    # Date of the latest explicit full-snapshot import that contained this account: its balance is current as of then.
    confirmed_through: Mapped[date | None] = mapped_column(Date, nullable=True)


class Import(Base):
    __tablename__ = "imports"
    __table_args__ = (UniqueConstraint("user_id", "sha256"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="processing")
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("user_id", "account_id", "source_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(128))
    booking_date: Mapped[date] = mapped_column(Date, index=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    merchant: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(300), default="Uncategorized")
    category_override: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Category assigned by the user's category rules; never touches the imported category.
    rule_category: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_uncertain: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    split_parent_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    split_role: Mapped[str] = mapped_column(String(20), default="none")
    contract_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[dict] = mapped_column(JSON, default=dict)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"))
    missing_from_latest: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def effective_category(self) -> str:
        """Manual correction first, then the user's category rule, then the imported category."""
        return self.category_override or self.rule_category or self.category
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TransactionRevision(Base):
    __tablename__ = "transaction_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"))
    source: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Balance(Base):
    __tablename__ = "balances"
    __table_args__ = (UniqueConstraint("account_id", "observed_date", "import_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("imports.id"))
    observed_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))


class Bucket(Base):
    __tablename__ = "buckets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    kind: Mapped[str] = mapped_column(String(20), default="virtual")
    target: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (UniqueConstraint("bucket_id", "account_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    bucket_id: Mapped[str] = mapped_column(ForeignKey("buckets.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))


class AllocationEvent(Base):
    """Append-only history of what was earmarked for a bucket; allocations themselves are replaced on each save."""
    __tablename__ = "allocation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    bucket_id: Mapped[str] = mapped_column(String(36), index=True)
    bucket_name: Mapped[str] = mapped_column(String(300))
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(36))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AccountChange(Base):
    """Settings of an account before and after a change, so past views can use the settings that applied then."""
    __tablename__ = "account_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)


class Obligation(Base):
    __tablename__ = "obligations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    bucket_id: Mapped[str] = mapped_column(ForeignKey("buckets.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    period: Mapped[str] = mapped_column(String(20))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    scheduled_contributions: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(50), default="info")
    status: Mapped[str] = mapped_column(String(30), default="open")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Wish(Base):
    __tablename__ = "wishes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_monthly_cost: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WishlistPrefs(Base):
    __tablename__ = "wishlist_prefs"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    self_names: Mapped[list] = mapped_column(JSON, default=list)
    reserve_months: Mapped[int] = mapped_column(Integer, default=3)
    monthly_tax_reserve: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))


class IncomeRule(Base):
    __tablename__ = "income_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20))
    pattern: Mapped[str] = mapped_column(String(200), default="")
    match_field: Mapped[str] = mapped_column(String(20), default="any")
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    shift_from_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Holding(Base):
    """Manually tracked asset or liability (car, loan, property, depot) with the user's ownership share."""
    __tablename__ = "holdings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(40), default="other")
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    share: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal(100))
    monthly_payment: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    valued_on: Mapped[date] = mapped_column(Date, default=date.today)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class HoldingSnapshot(Base):
    """Value of a holding on a day; one row per day, written whenever the value is set or changed."""
    __tablename__ = "holding_snapshots"
    __table_args__ = (UniqueConstraint("holding_id", "observed_on", name="uq_holding_snapshot_day"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    holding_id: Mapped[str] = mapped_column(ForeignKey("holdings.id", ondelete="CASCADE"), index=True)
    observed_on: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))


class BusinessRule(Base):
    """Marks matching spending as business expense so it is reported apart from private consumption."""
    __tablename__ = "business_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    pattern: Mapped[str] = mapped_column(String(200), default="")
    match_field: Mapped[str] = mapped_column(String(20), default="any")
    category: Mapped[str | None] = mapped_column(String(300), nullable=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ContractDecision(Base):
    """User decision about a detected recurring contract, stored by normalized payee key (survives re-imports)."""
    __tablename__ = "contract_decisions"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(300))
    decision: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CategoryRule(Base):
    """Assigns a category to matching bookings without touching the imported data (first matching rule wins)."""
    __tablename__ = "category_rules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    pattern: Mapped[str] = mapped_column(String(200), default="")
    match_field: Mapped[str] = mapped_column(String(20), default="any")
    flow: Mapped[str] = mapped_column(String(10), default="any")
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TransferRejection(Base):
    """A detected transfer pair the user rejected; the pair is never marked as a transfer again."""
    __tablename__ = "transfer_rejections"
    __table_args__ = (UniqueConstraint("user_id", "key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    booking_date: Mapped[date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlanItem(Base):
    """A monthly target (SOLL) the owner maintains, compared against actual spending from a pot and/or a category."""
    __tablename__ = "plan_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
