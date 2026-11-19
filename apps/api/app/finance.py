from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .models import Account, Allocation, Balance, Bucket, Import, Obligation, Setting, Transaction

ZERO = Decimal("0")


def local_today(db, user_id):
    preferences = db.get(Setting, user_id)
    timezone_name = preferences.data.get("timezone", "Europe/Berlin") if preferences else "Europe/Berlin"
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        zone = ZoneInfo("Europe/Berlin")
    return datetime.now(zone).date()


def decimal_string(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def serialize(value):
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if hasattr(value, "__table__"):
        return {column.name: serialize(getattr(value, column.name)) for column in value.__table__.columns}
    return value


def latest_balance(db, account_id, as_of=None):
    query = select(Balance).where(Balance.account_id == account_id, Balance.observed_date <= (as_of or date.today()))
    return db.scalar(query.join(Import, Import.id == Balance.import_id).order_by(Balance.observed_date.desc(), Import.created_at.desc(), Balance.id.desc()).limit(1))


def effective_observed_date(account, observation):
    """A balance is current as of the later of its booking date and the latest full import that contained the account."""
    confirmed = getattr(account, "confirmed_through", None)
    return max(observation.observed_date, confirmed) if confirmed else observation.observed_date


def balance_is_stale(account, observation, as_of, days=7):
    return (as_of - effective_observed_date(account, observation)).days > days


def account_json(db, account):
    observation = latest_balance(db, account.id, local_today(db, account.user_id))
    data = serialize(account)
    data.pop("user_id")
    data.update(balance=serialize(observation.amount) if observation else None,
                balance_date=observation.observed_date.isoformat() if observation else None,
                warnings=["Observed balance is not a complete asset valuation"] +
                         (["Ownership unverified"] if account.ownership == "unknown" else []) +
                         (["No observed balance"] if not observation else []))
    return data


def eligible(tx):
    return not tx.is_transfer and tx.split_role not in {"parent", "excluded"}


def annual(amount, period):
    return amount * {"monthly": Decimal(12), "quarterly": Decimal(4), "yearly": Decimal(1), "once": ZERO}[period]


def funding_eligible(account):
    return account.included and account.ownership == "owned" and account.purpose != "investment"


def allocation_backing(db, user_id, today=None):
    """Assign positive eligible observed capacity exactly once across all buckets.

    Nominal allocations remain editable intent. A balance drop cannot invent funds:
    stable bucket UUID order (then allocation UUID) determines backing priority.
    Negative balances remain liabilities in overview, but cannot back an allocation.
    """
    today = today or local_today(db, user_id)
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    rows = list(db.execute(select(Allocation, Bucket).join(Bucket, Bucket.id == Allocation.bucket_id)
                          .where(Bucket.user_id == user_id).order_by(Bucket.id, Allocation.id)))
    capacities = {}
    result = {}
    for allocation, bucket in rows:
        account = accounts.get(allocation.account_id)
        warnings = []
        if account is None or not funding_eligible(account) or account.currency != bucket.currency:
            backed, status = ZERO, "ineligible"
            warnings.append("Allocation backing is ineligible: account must be included, owned, liquid and same-currency")
        else:
            if account.id not in capacities:
                observation = latest_balance(db, account.id, today)
                capacities[account.id] = max(ZERO, observation.amount) if observation else None
            capacity = capacities[account.id]
            if capacity is None:
                backed, status = ZERO, "unobserved"
                warnings.append("Allocation has no observed balance backing")
            else:
                backed = min(allocation.amount, capacity)
                capacities[account.id] -= backed
                status = "backed" if backed == allocation.amount else "partial" if backed else "unbacked"
                if backed < allocation.amount:
                    warnings.append("Allocation is underfunded by latest observed funds; nominal intent is not funded money")
        result[allocation.id] = {"backed_amount": backed, "funding_shortfall": allocation.amount - backed,
                                  "funding_status": status, "warnings": warnings}
    return result


def bucket_json(db, bucket, today=None, backing=None):
    today = today or local_today(db, bucket.user_id)
    allocations = list(db.scalars(select(Allocation).where(Allocation.bucket_id == bucket.id)))
    obligations = sorted(db.scalars(select(Obligation).where(Obligation.bucket_id == bucket.id)),
                         key=lambda item: (item.due_date or bucket.due_date or today, item.id))
    backing = backing if backing is not None else allocation_backing(db, bucket.user_id, today)
    nominal = sum((a.amount for a in allocations), ZERO)
    funded = sum((backing[a.id]["backed_amount"] for a in allocations), ZERO)
    monthly = sum((annual(o.amount, o.period) / 12 for o in obligations), ZERO)
    available = funded
    required = ZERO
    warnings = []
    for allocation in allocations:
        warnings.extend(backing[allocation.id]["warnings"])
    # Shared bucket funds are consumed once across all obligations, earliest due first.
    for item in obligations:
        # Contributions belong only to this obligation and are assumed scheduled
        # to arrive by its next due date. Excess never funds another obligation.
        remaining_debit = max(ZERO, item.amount - item.scheduled_contributions)
        covered = min(available, remaining_debit)
        available -= covered
        gap = remaining_debit - covered
        due = item.due_date or bucket.due_date
        periods = max(1, (due.year - today.year) * 12 + due.month - today.month) if due else 1
        required += gap / periods
    if not obligations and bucket.target:
        due = bucket.due_date
        periods = max(1, (due.year - today.year) * 12 + due.month - today.month) if due else 1
        required = max(ZERO, bucket.target - funded) / periods
    return serialize({**serialize(bucket), "allocations": [{**serialize(a), **backing[a.id]} for a in allocations], "obligations": obligations,
                      "nominal_allocated": nominal, "funded": funded, "funding_shortfall": nominal - funded,
                      "monthly_obligation": monthly, "required_monthly_contribution": required,
                      "warnings": sorted(set(warnings))})


def overview(db, user_id, start=None, end=None):
    today = local_today(db, user_id)
    end = end or today
    start = start or today.replace(day=1)
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id)))
    included = {a.id: a for a in accounts if a.included and a.ownership != "external"}
    txs = list(db.scalars(select(Transaction).where(Transaction.user_id == user_id,
                      Transaction.booking_date >= start, Transaction.booking_date <= min(end, today))))
    currencies, categories, trends = {}, defaultdict(lambda: ZERO), {}

    def totals(currency):
        return currencies.setdefault(currency, {"currency": currency, "income": ZERO, "expenses": ZERO,
                  "observed_balance": ZERO, "liquid_balance": ZERO, "allocated": ZERO,
                  "nominal_allocated": ZERO, "funding_shortfall": ZERO, "monthly_obligations": ZERO})

    warnings = {"Observed balances may have incomplete coverage; not a complete net worth", "Debt-service and full asset coverage unavailable"}
    if end < today:
        warnings.add("Historical views use current account inclusion, purpose and planned obligations; these are not versioned")
    if start.day != 1 or end >= today or (end + timedelta(days=1)).day != 1:
        warnings.add("Period contains incomplete months")
    for tx in txs:
        if tx.account_id not in included:
            continue
        if tx.transfer_uncertain:
            warnings.add("One-sided transfers excluded; ownership uncertain")
        if tx.split_role in {"uncertain", "excluded", "orphan"}:
            warnings.add("Split reconciliation uncertain")
        if tx.missing_from_latest:
            warnings.add("Records missing from a later full snapshot retained")
        if not eligible(tx):
            continue
        item = totals(tx.currency)
        trend = trends.setdefault((tx.booking_date.strftime("%Y-%m"), tx.currency),
                                   {"month": tx.booking_date.strftime("%Y-%m"), "currency": tx.currency, "income": ZERO, "expenses": ZERO})
        key = "income" if tx.amount >= 0 else "expenses"
        item[key] += abs(tx.amount)
        trend[key] += abs(tx.amount)
        if tx.amount < 0:
            categories[(tx.currency, tx.category_override or tx.category)] += -tx.amount
    for account in included.values():
        item = totals(account.currency)
        observation = latest_balance(db, account.id, min(end, today))
        if account.ownership == "unknown":
            warnings.add("Some account ownership remains unverified")
            warnings.add("Unverified account balances are excluded from available liquidity")
        if observation:
            item["observed_balance"] += observation.amount
            if funding_eligible(account):
                item["liquid_balance"] += observation.amount
            if balance_is_stale(account, observation, min(end, today)):
                warnings.add("Some observed balances are stale")
        else:
            warnings.add("Some accounts have no observed balance")
    buckets = list(db.scalars(select(Bucket).where(Bucket.user_id == user_id)))
    backing = allocation_backing(db, user_id, today) if end >= today else {}
    for bucket in buckets:
        item = totals(bucket.currency)
        allocations = list(db.scalars(select(Allocation).where(Allocation.bucket_id == bucket.id)))
        # Current allocations are not historical facts.
        if end < today and allocations:
            warnings.add("Historical allocation snapshots unavailable; current allocations not subtracted")
        else:
            for allocation in allocations:
                state = backing[allocation.id]
                item["allocated"] += state["backed_amount"]
                item["nominal_allocated"] += allocation.amount
                item["funding_shortfall"] += state["funding_shortfall"]
                warnings.update(state["warnings"])
        obligations = list(db.scalars(select(Obligation).where(Obligation.bucket_id == bucket.id)))
        item["monthly_obligations"] += sum((annual(o.amount, o.period) / 12 for o in obligations), ZERO)
    for item in currencies.values():
        item["surplus"] = item["income"] - item["expenses"]
        item["savings_rate"] = item["surplus"] / item["income"] if item["income"] else None
        item["available_liquidity"] = item["liquid_balance"] - item["allocated"]
    for item in trends.values():
        item["surplus"] = item["income"] - item["expenses"]
    return serialize({"currencies": sorted(currencies.values(), key=lambda i: i["currency"]),
            "categories": [{"currency": c, "category": cat, "amount": amount} for (c, cat), amount in sorted(categories.items())],
            "trends": [trends[k] for k in sorted(trends)], "warnings": sorted(warnings), "start": start, "end": end})


def contracts(db, user_id):
    txs = list(db.scalars(select(Transaction).where(Transaction.user_id == user_id,
               Transaction.booking_date <= local_today(db, user_id), Transaction.amount < 0).order_by(Transaction.booking_date)))
    groups = defaultdict(list)
    for tx in txs:
        if eligible(tx):
            groups[(tx.contract_name or tx.merchant, tx.currency, bool(tx.contract_name))].append(tx)
    items = []
    for (name, currency, source), rows in groups.items():
        if not name or (not source and len(rows) < 3):
            continue
        gaps = [(b.booking_date - a.booking_date).days for a, b in zip(rows, rows[1:])]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
        period = None
        days = None
        if source:
            declared = str(rows[-1].source.get("contract_period") or "").strip().casefold()
            declared_periods = {"monatlich": ("monthly", 30), "monthly": ("monthly", 30), "1": ("monthly", 30),
                                "vierteljährlich": ("quarterly", 91), "vierteljaehrlich": ("quarterly", 91),
                                "quartalsweise": ("quarterly", 91), "quarterly": ("quarterly", 91), "3": ("quarterly", 91),
                                "jährlich": ("yearly", 365), "jaehrlich": ("yearly", 365), "yearly": ("yearly", 365), "12": ("yearly", 365)}
            period, days = declared_periods.get(declared, (None, None))
        for candidate, low, high, typical in [("monthly", 25, 35, 30), ("quarterly", 80, 100, 91), ("yearly", 350, 380, 365)]:
            if period is None and median_gap is not None and low <= median_gap <= high and all(low <= gap <= high for gap in gaps):
                period, days = candidate, typical
        if not source and not period:
            continue
        last = rows[-1]
        cost = annual(-last.amount, period) if period else None
        items.append({"name": name, "currency": currency, "source": "export" if source else "inferred",
                      "confidence": "high" if source else "medium", "period": period or "unknown",
                      "annual_cost": cost, "monthly_cost": cost / 12 if cost else None,
                      "next_charge": last.booking_date + timedelta(days=days) if days else None,
                      "price_change": (-last.amount) - (-rows[-2].amount) if len(rows) > 1 else None,
                      "evidence": [row.id for row in rows]})
    return serialize({"items": items, "warnings": ["Inferred recurrence and next dates are estimates, not contractual commitments"]})
