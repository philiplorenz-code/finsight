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
    return amount * {"monthly": Decimal(12), "quarterly": Decimal(4), "half_yearly": Decimal(2), "yearly": Decimal(1), "once": ZERO}[period]


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
    goal = None
    if bucket.target:
        # Savings goal traffic light: the needed monthly rate against standing orders into the backing accounts.
        from .plan import standing_orders
        backing_ids = {a.account_id for a in allocations}
        planned = sum((o["amount"] for o in standing_orders(db, bucket.user_id, today) if o["active"] and o["account_id"] in backing_ids), ZERO)
        months_left = max(1, (bucket.due_date.year - today.year) * 12 + bucket.due_date.month - today.month) if bucket.due_date else None
        if funded >= bucket.target:
            status = "done"
        elif not bucket.due_date:
            status = "no_deadline"
        elif bucket.due_date < today:
            status = "overdue"
        elif planned >= required:
            status = "on_track"
        elif planned >= required * Decimal("0.7"):
            status = "tight"
        else:
            status = "behind"
        goal = {"target": bucket.target, "funded": funded, "progress": min(Decimal(1), funded / bucket.target) if bucket.target else None,
                "required_monthly": required, "planned_monthly": planned, "months_left": months_left, "status": status,
                "projected_at_due": (funded + planned * months_left) if months_left else None}
    return serialize({**serialize(bucket), "allocations": [{**serialize(a), **backing[a.id]} for a in allocations], "obligations": obligations,
                      "nominal_allocated": nominal, "funded": funded, "funding_shortfall": nominal - funded,
                      "monthly_obligation": monthly, "required_monthly_contribution": required, "goal": goal,
                      "warnings": sorted(set(warnings))})


def overview(db, user_id, start=None, end=None):
    today = local_today(db, user_id)
    end = end or today
    start = start or today.replace(day=1)
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id)))
    included = {a.id: a for a in accounts if a.included and a.ownership != "external"}
    # Pay booked at month end can belong to the next month (income rule `shift_from_day`), so look one
    # month back and place every booking on its effective day before filtering by the period.
    from .income import load_rules, match_rule, shifts_to_next_month
    from .cashbook import entries as cash_entries, is_withdrawal, since as cash_book_since
    cash_since = cash_book_since(db, user_id)
    rules = load_rules(db, user_id)
    txs = list(db.scalars(select(Transaction).where(Transaction.user_id == user_id,
                      Transaction.booking_date >= start - timedelta(days=31), Transaction.booking_date <= min(end, today))))

    def effective_day(tx):
        if tx.amount > 0 and rules and shifts_to_next_month(tx, match_rule(tx, rules)):
            d = tx.booking_date
            return date(d.year + d.month // 12, d.month % 12 + 1, 1)
        return tx.booking_date
    currencies, categories, trends = {}, defaultdict(lambda: ZERO), {}

    def totals(currency):
        return currencies.setdefault(currency, {"currency": currency, "income": ZERO, "expenses": ZERO,
                  "observed_balance": ZERO, "observed_mine": ZERO, "held_for_others": ZERO, "liquid_balance": ZERO, "allocated": ZERO,
                  "nominal_allocated": ZERO, "funding_shortfall": ZERO, "monthly_obligations": ZERO})

    warnings = {"Observed balances may have incomplete coverage; not a complete net worth", "Debt-service and full asset coverage unavailable"}
    if end < today:
        warnings.add("Historical views use current account inclusion, purpose and planned obligations; these are not versioned")
    if start.day != 1 or end >= today or (end + timedelta(days=1)).day != 1:
        warnings.add("Period contains incomplete months")
    for tx in txs:
        if tx.account_id not in included:
            continue
        day = effective_day(tx)
        if day < start or day > end:
            continue
        if tx.transfer_uncertain:
            warnings.add("One-sided transfers excluded; ownership uncertain")
        if tx.split_role in {"uncertain", "excluded", "orphan"}:
            warnings.add("Split reconciliation uncertain")
        if tx.missing_from_latest:
            warnings.add("Records missing from a later full snapshot retained")
        if not eligible(tx) or included[tx.account_id].purpose == "mirror":
            continue  # mirror accounts (e.g. PayPal) repeat payments already booked on the bank account
        if is_withdrawal(tx, cash_since):
            continue  # cash book active: the withdrawal only moves money into the wallet
        item = totals(tx.currency)
        trend = trends.setdefault((day.strftime("%Y-%m"), tx.currency),
                                   {"month": day.strftime("%Y-%m"), "currency": tx.currency, "income": ZERO, "expenses": ZERO})
        key = "income" if tx.amount >= 0 else "expenses"
        item[key] += abs(tx.amount)
        trend[key] += abs(tx.amount)
        if tx.amount < 0:
            categories[(tx.currency, tx.effective_category)] += -tx.amount
    for entry in cash_entries(db, user_id, start, min(end, today)):
        item = totals("EUR")
        trend = trends.setdefault((entry.day.strftime("%Y-%m"), "EUR"), {"month": entry.day.strftime("%Y-%m"), "currency": "EUR", "income": ZERO, "expenses": ZERO})
        item["expenses"] += entry.amount
        trend["expenses"] += entry.amount
        categories[("EUR", entry.category)] += entry.amount
    for account in included.values():
        item = totals(account.currency)
        observation = latest_balance(db, account.id, min(end, today))
        if account.ownership == "unknown":
            warnings.add("Some account ownership remains unverified")
            warnings.add("Unverified account balances are excluded from available liquidity")
        if observation:
            item["observed_balance"] += observation.amount
            mine = observation.amount * account.owner_share / Decimal(100)
            item["observed_mine"] += mine
            item["held_for_others"] += observation.amount - mine  # e.g. tax pots or money kept for family
            if funding_eligible(account):
                item["liquid_balance"] += mine
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


DECLARED_PERIODS = {"monatlich": ("monthly", 30), "monthly": ("monthly", 30), "1": ("monthly", 30),
                    "vierteljährlich": ("quarterly", 91), "vierteljaehrlich": ("quarterly", 91),
                    "quartalsweise": ("quarterly", 91), "quarterly": ("quarterly", 91), "3": ("quarterly", 91),
                    "halbjährlich": ("half_yearly", 182), "halbjaehrlich": ("half_yearly", 182),
                    "half_yearly": ("half_yearly", 182), "6": ("half_yearly", 182),
                    "jährlich": ("yearly", 365), "jaehrlich": ("yearly", 365), "yearly": ("yearly", 365), "12": ("yearly", 365)}


def contracts(db, user_id):
    from collections import Counter
    from .recurring import classify, group_key, infer_period, load_decisions, normalize_key, status_of
    today = local_today(db, user_id)
    txs = list(db.scalars(select(Transaction).where(Transaction.user_id == user_id,
               Transaction.booking_date <= today, Transaction.amount < 0).order_by(Transaction.booking_date)))
    decisions = load_decisions(db, user_id)
    groups = defaultdict(list)
    for tx in txs:
        if eligible(tx):
            declared, key = group_key(tx)
            groups[(declared, key, tx.currency)].append(tx)
    items = []
    for (source, gkey, currency), rows in groups.items():
        last = rows[-1]
        if gkey.startswith("n:"):
            name = gkey[2:].strip()  # the export names the contract itself
        else:
            names = Counter((r.merchant or "").strip() for r in rows if (r.merchant or "").strip())
            name = names.most_common(1)[0][0] if names else ""
        if not name:
            continue
        period, days = None, None
        if source:
            declared = str(last.source.get("contract_period") or "").strip().casefold()
            period, days = DECLARED_PERIODS.get(declared, (None, None))
            if period is None:
                inferred = infer_period([r.booking_date for r in rows], [-r.amount for r in rows])
                period, days = inferred if inferred else (None, None)
        else:
            if gkey in {"m:", ""}:
                continue
            inferred = infer_period([r.booking_date for r in rows], [-r.amount for r in rows])
            if not inferred:
                continue
            period, days = inferred
        if not source and not period:
            continue
        key = normalize_key(name) or gkey
        decision = decisions.get(key)
        cost = annual(-last.amount, period) if period else None
        kind = (decision.kind if decision and decision.kind else None) or classify(name, last.effective_category)
        items.append({"key": key, "name": (decision.name if decision and decision.name else name), "currency": currency,
                      "source": "export" if source else "inferred", "confidence": "high" if source else "medium",
                      "period": period or "unknown", "kind": kind,
                      "status": status_of(last.booking_date, days, today) if days else "active",
                      "decision": decision.decision if decision else None,
                      "annual_cost": cost, "monthly_cost": cost / 12 if cost else None,
                      "next_charge": last.booking_date + timedelta(days=days) if days else None,
                      "last_charge": last.booking_date, "charges": len(rows),
                      "price_change": (-last.amount) - (-rows[-2].amount) if len(rows) > 1 else None,
                      "evidence": [row.id for row in rows]})
    visible = [i for i in items if i["decision"] != "dismissed"]
    dismissed = [i for i in items if i["decision"] == "dismissed"]
    active = [i for i in visible if i["status"] == "active" and i["monthly_cost"] and i["kind"] != "savings"]  # savings plans are not costs
    totals = {}
    for item in active:
        t = totals.setdefault(item["currency"], {"monthly": ZERO, "yearly": ZERO, "by_kind": {}})
        t["monthly"] += item["monthly_cost"]
        t["yearly"] += item["annual_cost"]
        k = t["by_kind"].setdefault(item["kind"], {"monthly": ZERO, "yearly": ZERO, "count": 0})
        k["monthly"] += item["monthly_cost"]
        k["yearly"] += item["annual_cost"]
        k["count"] += 1
    # Where renegotiating or cancelling is realistic: insurances, subscriptions and uncategorised costs, biggest first.
    candidates = sorted((i for i in active if i["kind"] in {"insurance", "subscription", "other"}),
                        key=lambda i: -i["annual_cost"])[:10]
    return serialize({"items": visible, "dismissed": dismissed, "totals": totals,
                      "cancellation_candidates": [{"key": i["key"], "name": i["name"], "kind": i["kind"], "currency": i["currency"],
                                                   "annual_cost": i["annual_cost"], "period": i["period"],
                                                   "price_increase": bool(i["price_change"] and i["price_change"] > 0)} for i in candidates],
                      "warnings": ["Inferred recurrence and next dates are estimates, not contractual commitments"]})
