"""Opt-in, bounded aggregate-only AI. Import models before schema creation.

The API owner supplies authentication, sessions and deterministic finance queries
to ``create_router``; no provider is configured from request bodies.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_CEILING
from typing import Any, Awaitable, Callable, Literal, TypedDict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base
from .models import Finding, Setting, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIPolicy(Base):
    __tablename__ = "ai_policies"
    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    external_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    proactive_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str] = mapped_column(String(160), default="")
    # NULL on a legacy migration is intentionally NOT treated as EUR.
    budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True, default="EUR")
    # Operator-maintained, conservative EUR per million token rates.
    prices: Mapped[dict] = mapped_column(JSON, default=dict)
    total_limit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    channel_limits: Mapped[dict] = mapped_column(JSON, default=dict)
    run_limit: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    max_concurrent: Mapped[int] = mapped_column(Integer, default=1)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=512)
    max_tools: Mapped[int] = mapped_column(Integer, default=3)
    max_steps: Mapped[int] = mapped_column(Integer, default=6)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(160))
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, default="EUR")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="reserved")
    reserved: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    charged: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    input_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    output_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class AIBlocked(ValueError):
    """Safe public reason code; never contains provider messages or finance data."""


RUNTIME_BOUNDS = {"max_input_tokens": (128, 32000), "max_output_tokens": (1, 4096),
                  "max_tools": (1, 20), "max_steps": (3, 8), "timeout_seconds": (1, 120), "max_concurrent": (1, 8)}
RUNTIME_ENV = {"max_input_tokens": ("AI_MAX_INPUT_TOKENS", 8000),
               "max_output_tokens": ("AI_MAX_OUTPUT_TOKENS", 2000),
               "max_tools": ("AI_MAX_TOOL_CALLS", 20), "max_steps": ("AI_MAX_AGENT_STEPS", 8),
               "timeout_seconds": ("AI_MAX_RUNTIME_SECONDS", 90), "max_concurrent": ("AI_MAX_CONCURRENT_RUNS", 1)}


def env_bool(name: str) -> bool:
    value = os.environ.get(name, "false").lower()
    if value not in {"true", "false"}:
        raise AIBlocked("invalid_operator_boolean")
    return value == "true"


def runtime_environment() -> dict:
    limits = {}
    for field, (name, default) in RUNTIME_ENV.items():
        try:
            value = int(os.environ.get(name, str(default)))
        except ValueError:
            raise AIBlocked("invalid_runtime_environment") from None
        low, high = RUNTIME_BOUNDS[field]
        if not low <= value <= high:
            raise AIBlocked("invalid_runtime_environment")
        limits[field] = value
    if os.environ.get("AI_RETRY_LIMIT", "0") != "0":
        raise AIBlocked("provider_retries_unsupported")
    return limits


@dataclass(frozen=True)
class OperatorAI:
    model: str
    prices: dict
    runtime: dict
    monthly: Decimal
    scheduled: Decimal
    chat: Decimal
    per_run: Decimal
    total: Decimal
    proactive: bool


def provider_credentials() -> tuple[str, str]:
    base, key = os.environ.get("AI_PROVIDER_BASE_URL", ""), os.environ.get("AI_API_KEY", "")
    try:
        parsed = urlsplit(base)
        valid = parsed.scheme in {"https", "http"} and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment)
        parsed.port  # Also reject invalid port syntax without echoing the URL.
    except ValueError:
        valid = False
    if not valid or not key.strip() or any(c in key for c in "\r\n"):
        raise AIBlocked("provider_credentials_not_configured")
    return base, key


def operator_environment() -> OperatorAI:
    """Exact .env.example names; no .env file, credentials or network is read on import."""
    if not env_bool("AI_ENABLED") or not env_bool("AI_EXTERNAL_CONSENT"):
        raise AIBlocked("operator_external_ai_disabled")
    provider_credentials()
    model = os.environ.get("AI_MODEL", "")
    allowlist = {entry.strip() for entry in os.environ.get("AI_MODEL_ALLOWLIST", "").split(",") if entry.strip()}
    if not model or model not in allowlist or len(model) > 160:
        raise AIBlocked("model_not_allowlisted")
    # The single pair prices ONLY AI_MODEL, never every entry in the allowlist.
    ir = money(os.environ.get("AI_INPUT_EUR_PER_MILLION", ""))
    outr = money(os.environ.get("AI_OUTPUT_EUR_PER_MILLION", ""))
    monthly = money(os.environ.get("AI_MONTHLY_BUDGET_EUR", "5.00"))
    return OperatorAI(model=model, prices={model: {"input": str(ir), "output": str(outr), "currency": "EUR", "verified": True}},
                      runtime=runtime_environment(), monthly=monthly,
                      scheduled=money(os.environ.get("AI_SCHEDULED_BUDGET_EUR", "2.00")),
                      chat=money(os.environ.get("AI_CHAT_BUDGET_EUR", "3.00")),
                      per_run=money(os.environ.get("AI_MAX_RUN_COST_EUR", "0.25")),
                      total=money(os.environ.get("AI_TOTAL_BUDGET_EUR", str(monthly))),
                      proactive=env_bool("AI_PROACTIVE_ENABLED"))


def provision_from_environment(session: Session, owner_id: str, *, enabled: bool,
                               external_consent: bool, proactive_consent: bool) -> AIPolicy:
    """Explicit authenticated consent action, not automatic startup consent."""
    operator = operator_environment()
    if enabled and not external_consent or proactive_consent and not (enabled and external_consent and operator.proactive):
        raise AIBlocked("explicit_consent_required")
    # The real authenticated owner always exists. Lock serializes initial provision.
    session.scalar(select(User).where(User.id == str(owner_id)).with_for_update())
    policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update().execution_options(populate_existing=True))
    if policy is None:
        policy = AIPolicy(owner_id=str(owner_id), budget_currency="EUR")
        session.add(policy)
    elif policy.budget_currency != "EUR":
        raise AIBlocked("legacy_currency_reconciliation_required")
    if session.scalar(select(AIRun.id).where(AIRun.owner_id == str(owner_id),
            (AIRun.currency.is_(None) | (AIRun.currency != "EUR"))).limit(1)):
        raise AIBlocked("legacy_currency_reconciliation_required")
    policy.enabled, policy.external_consent, policy.proactive_consent = enabled, external_consent, proactive_consent
    policy.model, policy.prices = operator.model, operator.prices
    policy.total_limit, policy.monthly_limit, policy.run_limit = operator.total, operator.monthly, operator.per_run
    policy.channel_limits = {"chat": str(operator.chat), **{channel: str(operator.scheduled) for channel in ("weekly", "monthly", "changed_import")}}
    for key, value in operator.runtime.items():
        setattr(policy, key, value)
    session.flush()
    return policy


def money(value: Any) -> Decimal:
    # Reject JSON floats: operator pricing must be supplied as decimal strings.
    if isinstance(value, (float, bool)) or (isinstance(value, str) and len(value) > 64):
        raise AIBlocked("invalid_pricing_or_budget")
    try:
        amount = Decimal(value)
    except Exception as exc:
        raise AIBlocked("invalid_pricing_or_budget") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("999999999999") or amount.as_tuple().exponent < -8:
        raise AIBlocked("invalid_pricing_or_budget")
    return amount


def cost(input_tokens: int, output_tokens: int, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    return ((input_tokens * input_rate + output_tokens * output_rate) / Decimal(1_000_000)).quantize(
        Decimal("0.00000001"), rounding=ROUND_CEILING
    )


def reserve(session: Session, owner_id: str, channel: str = "chat", now: datetime | None = None,
            operator: OperatorAI | None = None) -> tuple[AIRun, dict]:
    """Caller must commit before network I/O. PostgreSQL policy-row lock serializes all reservations.

    Policy rows must be provisioned by the owner settings transaction, never upserted
    here. SQLite is useful for logic tests but does not verify row-lock semantics.
    """
    now = now or utcnow()
    if session.bind.dialect.name == "postgresql" and session.execute(text("SHOW transaction_isolation")).scalar_one() != "read committed":
        raise AIBlocked("read_committed_isolation_required")
    policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update().execution_options(populate_existing=True))
    if not policy or not policy.enabled or not policy.external_consent:
        raise AIBlocked("external_ai_disabled")
    if policy.budget_currency != "EUR":
        raise AIBlocked("legacy_currency_reconciliation_required")
    if channel not in {"chat", "weekly", "monthly", "changed_import"}:
        raise AIBlocked("invalid_channel")
    if channel != "chat" and not policy.proactive_consent:
        raise AIBlocked("proactive_disabled")
    if not policy.model or policy.model not in policy.prices:
        raise AIBlocked("model_not_allowlisted")
    price = policy.prices[policy.model]
    if not isinstance(price, dict) or price.get("currency") != "EUR" or price.get("verified") is not True:
        raise AIBlocked("unverified_pricing")
    ir, outr = money(price.get("input")), money(price.get("output"))
    if operator is not None:
        if policy.model != operator.model or policy.model not in operator.prices:
            raise AIBlocked("operator_model_mismatch")
        expected = operator.prices[policy.model]
        if ir != money(expected["input"]) or outr != money(expected["output"]):
            raise AIBlocked("operator_pricing_mismatch")
        if channel != "chat" and not operator.proactive:
            raise AIBlocked("operator_proactive_disabled")
    config = {}
    for key, (low, high) in RUNTIME_BOUNDS.items():
        value = getattr(policy, key)
        if type(value) is not int or not low <= value <= high:
            raise AIBlocked("invalid_runtime_bounds")
        config[key] = min(value, operator.runtime[key]) if operator else value
    worst = cost(config["max_input_tokens"], config["max_output_tokens"], ir, outr)
    if worst > min(money(policy.run_limit), operator.per_run if operator else money(policy.run_limit)):
        raise AIBlocked("run_budget_exhausted")
    runs = list(session.scalars(select(AIRun).where(AIRun.owner_id == str(owner_id))))
    if any(r.currency != "EUR" for r in runs):
        raise AIBlocked("legacy_currency_reconciliation_required")
    # Uncertain requests keep both their reservation and concurrency slot until an
    # operator reconciles provider billing. A crashed process cannot free a budget.
    if sum(r.state in {"reserved", "uncertain"} for r in runs) >= config["max_concurrent"]:
        raise AIBlocked("concurrency_exhausted")
    def liability(run: AIRun) -> Decimal:
        return run.charged if run.state in {"settled", "released"} and run.charged is not None else run.reserved
    month = now.astimezone(timezone.utc).strftime("%Y-%m")
    total = sum((liability(r) for r in runs), Decimal(0))
    def in_month(run: AIRun) -> bool:
        # Carry all unresolved liabilities across UTC month boundaries, and count
        # late settlements in both reservation and settlement months conservatively.
        return (run.state not in {"settled", "released"} or run.created_at.strftime("%Y-%m") == month or
                (run.settled_at is not None and run.settled_at.strftime("%Y-%m") == month))
    monthly = sum((liability(r) for r in runs if in_month(r)), Decimal(0))
    channel_month = sum((liability(r) for r in runs if r.channel == channel and in_month(r)), Decimal(0))
    total_cap = min(money(policy.total_limit), operator.total) if operator else money(policy.total_limit)
    month_cap = min(money(policy.monthly_limit), operator.monthly) if operator else money(policy.monthly_limit)
    if total + worst > total_cap or monthly + worst > month_cap:
        raise AIBlocked("budget_exhausted")
    channel_cap = money(policy.channel_limits.get(channel, "0"))
    if operator:
        channel_cap = min(channel_cap, operator.chat if channel == "chat" else operator.scheduled)
        scheduled = sum((liability(r) for r in runs if r.channel != "chat" and in_month(r)), Decimal(0))
        if channel != "chat" and scheduled + worst > operator.scheduled:
            raise AIBlocked("scheduled_budget_exhausted")
    if channel_month + worst > channel_cap:
        raise AIBlocked("channel_budget_exhausted")
    run = AIRun(owner_id=str(owner_id), channel=channel, model=policy.model, created_at=now,
                reserved=worst, input_rate=ir, output_rate=outr, state="reserved", currency="EUR")
    session.add(run)
    session.flush()
    return run, config


def settle(session: Session, run_id: str, owner_id: str, usage: dict | None, config: dict) -> bool:
    # Same lock order as reserve, including finding lifecycle callers.
    session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update())
    run = session.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.owner_id == str(owner_id)).with_for_update().execution_options(populate_existing=True))
    if not run or run.state != "reserved":
        raise AIBlocked("run_not_reservable")
    if run.currency != "EUR":
        raise AIBlocked("legacy_currency_reconciliation_required")
    inp, out = (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens")
    if type(inp) is not int or type(out) is not int or not (0 < inp <= config["max_input_tokens"] and 0 <= out <= config["max_output_tokens"]):
        run.state, run.error_code = "uncertain", "missing_or_excess_usage"
        return False
    actual = cost(inp, out, run.input_rate, run.output_rate)
    if actual > run.reserved:
        run.state, run.error_code = "uncertain", "reservation_exceeded"
        return False
    run.input_tokens, run.output_tokens, run.charged, run.state = inp, out, actual, "settled"
    run.settled_at = utcnow()
    return True


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal["cashflow", "categories", "coverage"]
    start: date
    end: date
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Resolver must re-run this typed, owner-scoped query locally. No bank IDs.
    query: ToolRequest
    as_of: datetime
    aggregates: list[Aggregate]


class Aggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Fixed semantic keys only; arbitrary category/merchant labels cannot leak PII.
    metric: Literal["income", "expense", "surplus", "coverage", "count", "uncategorized"]
    value: str = Field(pattern=r"^-?\d{1,18}(\.\d{1,8})?$", max_length=28)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Deliberately no free-form prompt: this release only sends minimized aggregates.
    topic: Literal["cashflow", "categories", "coverage"] = "cashflow"
    start: date
    end: date
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")


class ConsentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    external_consent: bool
    proactive_consent: bool = False
    budget_currency: Literal["EUR"] = "EUR"
    model: str = Field(max_length=160)
    total_limit: Decimal = Field(ge=0, le=10000, max_digits=13, decimal_places=8)
    monthly_limit: Decimal = Field(ge=0, le=10000, max_digits=13, decimal_places=8)
    run_limit: Decimal = Field(ge=0, le=100, max_digits=11, decimal_places=8)
    channel_limits: dict[Literal["chat", "weekly", "monthly", "changed_import"], Decimal]

    @field_validator("total_limit", "monthly_limit", "run_limit", mode="before")
    @classmethod
    def decimal_strings(cls, value):
        return money(value)

    @field_validator("channel_limits", mode="before")
    @classmethod
    def channel_decimal_strings(cls, value):
        if not isinstance(value, dict) or len(value) > 4:
            raise ValueError("invalid_channel_limits")
        result = {key: money(amount) for key, amount in value.items()}
        if any(amount > Decimal(10000) for amount in result.values()):
            raise ValueError("invalid_channel_limits")
        return result


class EnvironmentConsent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool
    external_consent: bool
    proactive_consent: bool = False


FinanceQuery = Callable[[str, ToolRequest], Awaitable[list[Aggregate]]]


class AgentState(TypedDict, total=False):
    request: ChatRequest
    plan: list[ToolRequest]
    aggregates: list[dict]
    evidence: list[dict]
    answer: str
    usage: dict | None
    steps: int
    tools: int


async def litellm_provider(model: str, messages: list[dict], max_tokens: int, timeout: int,
                           *, on_transmit: Callable[[], None] | None = None) -> tuple[str, dict | None]:
    # Lazy import keeps the entire integration usable without an AI installation.
    os.environ["LITELLM_TELEMETRY"] = "False"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    # All local validation/imports precede the conservative transmission boundary.
    base, key = provider_credentials()
    try:
        import litellm
    except ImportError:
        raise AIBlocked("provider_dependency_unavailable") from None
    litellm.telemetry = False
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    if on_transmit:
        on_transmit()
    response = await litellm.acompletion(model=model, messages=messages, max_tokens=max_tokens,
                                        timeout=timeout, num_retries=0, stream=False, api_base=base, api_key=key)
    usage = response.usage.model_dump() if response.usage is not None else None
    return response.choices[0].message.content or "", usage


async def run_graph(request: ChatRequest, owner_id: str, model: str, config: dict,
                    query: FinanceQuery, provider=litellm_provider) -> AgentState:
    """Real LangGraph with a fixed typed read-only plan, no SQL or model-selected tools."""
    from langgraph.graph import END, START, StateGraph

    if request.end < request.start or (request.end - request.start).days > 366:
        raise AIBlocked("invalid_date_range")
    def tick(state: AgentState) -> int:
        steps = state.get("steps", 0) + 1
        if steps > config["max_steps"]:
            raise AIBlocked("step_limit")
        return steps
    async def plan(state: AgentState) -> dict:
        tools = [ToolRequest(tool=request.topic, start=request.start, end=request.end, currency=request.currency)]
        return {"plan": tools, "steps": tick(state)}
    async def tools(state: AgentState) -> dict:
        if len(state["plan"]) > config["max_tools"]:
            raise AIBlocked("tool_limit")
        aggregates, evidence = [], []
        for item in state["plan"]:
            rows = await query(str(owner_id), item)
            if len(rows) > 24:
                raise AIBlocked("aggregate_limit")
            snapshots = []
            for row in rows:
                aggregate = Aggregate.model_validate(row)
                if aggregate.currency != request.currency:
                    raise AIBlocked("currency_mismatch")
                aggregates.append(aggregate.model_dump())
                snapshots.append(aggregate)
            evidence.append(Evidence(query=item, as_of=utcnow(), aggregates=snapshots).model_dump(mode="json"))
        return {"aggregates": aggregates, "evidence": evidence, "tools": len(state["plan"]), "steps": tick(state)}
    async def explain(state: AgentState) -> dict:
        steps = tick(state)
        messages = [{"role": "system", "content": "Explain only these aggregate financial facts. Do not invent causes or advice. State incomplete coverage. Output plain text."},
                    {"role": "user", "content": json.dumps({"topic": request.topic, "aggregates": state["aggregates"]}, separators=(",", ":"))}]
        # UTF-8 bytes upper-bound common tokenizer counts with a generous envelope.
        # Reject rather than truncate; actual provider usage is checked on settlement.
        if len(json.dumps(messages).encode("utf-8")) + 256 > config["max_input_tokens"]:
            raise AIBlocked("input_token_limit")
        answer, usage = await provider(model, messages, config["max_output_tokens"], config["timeout_seconds"])
        if not isinstance(answer, str) or not answer.strip() or len(answer.encode("utf-8")) > config["max_output_tokens"] * 16:
            raise AIBlocked("output_limit")
        return {"answer": answer, "usage": usage, "steps": steps}
    graph = StateGraph(AgentState)
    graph.add_node("plan_query", plan)
    graph.add_node("read_tools", tools)
    graph.add_node("explain", explain)
    graph.add_edge(START, "plan_query")
    graph.add_edge("plan_query", "read_tools")
    graph.add_edge("read_tools", "explain")
    graph.add_edge("explain", END)
    async with asyncio.timeout(config["timeout_seconds"]):
        return await graph.compile().ainvoke({"request": request, "steps": 0, "tools": 0}, {"recursion_limit": config["max_steps"] + 2})


async def execute_chat(session: Session, owner_id: str, request: ChatRequest, query: FinanceQuery,
                       channel: str = "chat", provider=litellm_provider) -> dict:
    if request.end < request.start or (request.end - request.start).days > 366:
        raise AIBlocked("invalid_date_range")
    if provider is litellm_provider and session.bind.dialect.name != "postgresql":
        raise AIBlocked("postgresql_required_for_external_ai")
    # Missing operator opt-in/credentials/rates fails before any durable reservation.
    operator = operator_environment() if provider is litellm_provider else None
    run, config = reserve(session, str(owner_id), channel, operator=operator)
    run_id, model = run.id, run.model
    session.commit()  # Durable reservation MUST precede any provider request.
    transmitted = False
    def mark_transmitted():
        nonlocal transmitted
        transmitted = True
    async def tracked_provider(*args):
        if provider is litellm_provider:
            return await provider(*args, on_transmit=mark_transmitted)
        # Injected adapters are trusted server code; conservatively consider the
        # invocation a transmission unless they expose the built-in boundary.
        mark_transmitted()
        return await provider(*args)
    try:
        result = await run_graph(request, str(owner_id), model, config, query, tracked_provider)
        valid = settle(session, run_id, str(owner_id), result.get("usage"), config)
        run = session.get(AIRun, run_id)
        run.evidence = result["evidence"]
        if valid:
            session.add(Finding(user_id=str(owner_id), title=request.topic, kind="ai", body=result["answer"],
                                evidence=[{"run_id": run_id, **item} for item in result["evidence"]]))
        session.commit()
        if not valid:
            raise AIBlocked("provider_usage_unverified")
        return {"run_id": run_id, "answer": result["answer"], "evidence": result["evidence"]}
    except BaseException:
        session.rollback()
        # Release only a proven zero-call failure. Once transmission was possible,
        # cancellation/timeouts/errors retain full liability and concurrency.
        session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update())
        failed = session.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.owner_id == str(owner_id))
                                .with_for_update().execution_options(populate_existing=True))
        if failed and failed.state == "reserved":
            if transmitted:
                failed.state, failed.error_code = "uncertain", "execution_failed"
            else:
                failed.state, failed.error_code, failed.charged = "released", "pre_provider_failure", Decimal(0)
                failed.settled_at = utcnow()
            session.commit()
        else:
            session.rollback()
        raise


def create_router(get_session: Callable, require_owner: Callable, query: FinanceQuery, *, include_findings: bool = True) -> APIRouter:
    """Dependencies: yielded Session; authenticated owner ID (str/int), with CSRF on mutations."""
    router = APIRouter(tags=["AI"])

    @router.post("/ai/consent")
    @router.patch("/ai/consent")
    def environment_consent(body: EnvironmentConsent, session: Session = Depends(get_session), owner=Depends(require_owner)):
        try:
            if not body.enabled and not body.external_consent and not body.proactive_consent:
                policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner)).with_for_update())
                if policy:
                    policy.enabled = policy.external_consent = policy.proactive_consent = False
            else:
                policy = provision_from_environment(session, str(owner), **body.model_dump())
            session.commit()
        except AIBlocked as exc:
            session.rollback()
            raise HTTPException(409, str(exc)) from None
        return {"configured": policy is not None, "enabled": bool(policy and policy.enabled),
                "external_consent": bool(policy and policy.external_consent),
                "proactive_consent": bool(policy and policy.proactive_consent), "budget_currency": "EUR"}

    @router.get("/ai/settings")
    def ai_settings(session: Session = Depends(get_session), owner=Depends(require_owner)):
        policy = session.get(AIPolicy, str(owner))
        if not policy:
            return {"configured": False, "enabled": False, "external_consent": False, "proactive_consent": False,
                    "models": [], "budget_currency": "EUR", "agent_mode": "fixed_topic"}
        return {"configured": True, "enabled": policy.enabled, "external_consent": policy.external_consent,
                "proactive_consent": policy.proactive_consent, "model": policy.model, "models": sorted(policy.prices),
                "total_limit": str(policy.total_limit), "monthly_limit": str(policy.monthly_limit),
                "run_limit": str(policy.run_limit), "channel_limits": policy.channel_limits,
                "budget_currency": policy.budget_currency or "unknown", "agent_mode": "fixed_topic",
                "runtime_limits": {key: getattr(policy, key) for key in RUNTIME_BOUNDS}}

    @router.patch("/ai/settings")
    def ai_consent(body: ConsentUpdate, session: Session = Depends(get_session), owner=Depends(require_owner)):
        policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner)).with_for_update().execution_options(populate_existing=True))
        if not policy:
            raise HTTPException(409, "operator_pricing_not_configured")
        if policy.budget_currency != "EUR":
            raise HTTPException(409, "legacy_currency_reconciliation_required")
        if body.enabled and (not body.external_consent or body.model not in policy.prices):
            raise HTTPException(409, "consent_and_allowlisted_model_required")
        price = policy.prices.get(body.model, {})
        if body.enabled and (price.get("currency") != "EUR" or price.get("verified") is not True):
            raise HTTPException(409, "verified_eur_pricing_required")
        if body.proactive_consent and not (body.enabled and body.external_consent):
            raise HTTPException(409, "external_consent_required")
        for key, value in body.model_dump().items():
            setattr(policy, key, {k: str(v) for k, v in value.items()} if key == "channel_limits" else value)
        session.commit()
        return {"enabled": policy.enabled, "external_consent": policy.external_consent,
                "proactive_consent": policy.proactive_consent, "budget_currency": "EUR"}

    @router.post("/ai/chat")
    async def chat(body: ChatRequest, session: Session = Depends(get_session), owner=Depends(require_owner)):
        try:
            return await execute_chat(session, str(owner), body, query)
        except AIBlocked as exc:
            session.rollback()
            raise HTTPException(409, str(exc)) from None
        except Exception:
            raise HTTPException(503, "ai_execution_unavailable") from None

    @router.get("/ai/usage")
    def usage(session: Session = Depends(get_session), owner=Depends(require_owner)):
        runs = session.scalars(select(AIRun).where(AIRun.owner_id == str(owner)).order_by(AIRun.created_at.desc()).limit(100))
        return {"currency": "EUR", "runs": [{"id": r.id, "channel": r.channel, "state": r.state,
                "currency": r.currency or "unknown",
                "reserved": str(r.reserved), "charged": str(r.charged) if r.charged is not None else None,
                "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                "created_at": r.created_at.isoformat(), "error_code": r.error_code} for r in runs]}

    @router.get("/ai/runs/{run_id}/evidence")
    def run_evidence(run_id: str, session: Session = Depends(get_session), owner=Depends(require_owner)):
        run = session.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.owner_id == str(owner)))
        if not run:
            raise HTTPException(404, "not_found")
        return {"run_id": run.id, "evidence": run.evidence}

    @router.get("/findings")
    def findings(session: Session = Depends(get_session), owner=Depends(require_owner)):
        rows = session.scalars(select(Finding).where(Finding.user_id == str(owner)).order_by(Finding.created_at.desc()).limit(100))
        return [{"id": f.id, "title": f.title, "body": f.body, "kind": f.kind,
                 "status": f.status, "evidence": f.evidence} for f in rows]

    @router.patch("/findings/{finding_id}")
    def finding_state(finding_id: str, body: FindingState,
                      session: Session = Depends(get_session), owner=Depends(require_owner)):
        finding = session.scalar(select(Finding).where(Finding.id == finding_id, Finding.user_id == str(owner)))
        if not finding:
            raise HTTPException(404, "not_found")
        finding.status = body.status
        session.commit()
        return {"id": finding.id, "status": body.status}

    if not include_findings:
        router.routes = [route for route in router.routes if not route.path.startswith("/findings")]
    return router


class FindingState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "acknowledged", "dismissed"]


async def finance_query(owner_id: str, request: ToolRequest) -> list[Aggregate]:
    """Adapter to the core owner-scoped Decimal finance engine; labels never leave here."""
    # Each operation owns its session. Cancelling the graph cannot cause a late
    # result from the managed executor to reach a provider.
    return await asyncio.to_thread(_finance_query_sync, owner_id, request)


def _finance_query_sync(owner_id: str, request: ToolRequest) -> list[Aggregate]:
    from .db import SessionLocal
    from .finance import overview
    with SessionLocal() as session:
        if session.bind.dialect.name == "postgresql":
            session.execute(text("SET LOCAL statement_timeout = '5000'"))
        data = overview(session, str(owner_id), request.start, request.end)
    selected = next((row for row in data["currencies"] if row["currency"] == request.currency), None)
    if request.tool == "coverage":
        # Never claim full financial coverage. Zero means not established.
        return [Aggregate(metric="coverage", value="0", currency=request.currency)]
    if not selected:
        return [Aggregate(metric="count", value="0", currency=request.currency)]
    # Category labels can contain names; only the combined expense is disclosed.
    metrics = [("expense", "expenses")] if request.tool == "categories" else [
        ("income", "income"), ("expense", "expenses"), ("surplus", "surplus")]
    return [Aggregate(metric=metric, value=selected[key], currency=request.currency) for metric, key in metrics]


def enqueue_report(session: Session, owner_id: str, request: ChatRequest, channel: str, dedupe_key: str):
    """Explicit opt-in proactive trigger. Never replay an ambiguous billable request."""
    from .jobs import enqueue
    if channel not in {"weekly", "monthly", "changed_import"}:
        raise AIBlocked("invalid_channel")
    if request.end < request.start or (request.end - request.start).days > 366:
        raise AIBlocked("invalid_date_range")
    policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update().execution_options(populate_existing=True))
    if not policy or not policy.enabled or not policy.external_consent or not policy.proactive_consent:
        raise AIBlocked("proactive_disabled")
    return enqueue(session, str(owner_id), "ai_report", {"request": request.model_dump(mode="json"), "channel": channel},
                   dedupe_key="report:" + dedupe_key, replay_safe=False, max_attempts=1)


def report_handler(session_factory: Callable, query: FinanceQuery = finance_query, *, provider=litellm_provider):
    async def handle(item):
        request = ChatRequest.model_validate(item.payload["request"])
        with session_factory() as session:
            result = await execute_chat(session, item.owner_id, request, query, item.payload["channel"], provider)
            from .notifications import queue_notification
            queue_notification(session, item.owner_id, "report_ready", "report:" + result["run_id"])
            session.commit()
    return handle


def import_has_changes(summary: dict | None) -> bool:
    return isinstance(summary, dict) and any(type(summary.get(key)) is int and summary[key] > 0 for key in ("added", "changed"))


def schedule_reports(session: Session, owner_id: str, latest_import_id: str, latest_import_at: datetime,
                     *, now: datetime | None = None, timezone_name: str | None = None, currency: str | None = None,
                     latest_import_summary: dict | None = None) -> list[str]:
    """Fresh-import/weekly/monthly triggers; separate consent AND positive channel caps."""
    from datetime import timedelta
    now = now or utcnow()
    latest_import_at = latest_import_at.replace(tzinfo=timezone.utc) if latest_import_at.tzinfo is None else latest_import_at
    if not timedelta(0) <= now - latest_import_at <= timedelta(days=7):
        return []
    policy = session.scalar(select(AIPolicy).where(AIPolicy.owner_id == str(owner_id)).with_for_update().execution_options(populate_existing=True))
    if not policy or not policy.enabled or not policy.external_consent or not policy.proactive_consent:
        return []
    # Report denomination and calendar belong to the owner, not notification prefs.
    setting = session.get(Setting, str(owner_id))
    preferences = setting.data if setting and isinstance(setting.data, dict) else {}
    currency = currency if currency is not None else preferences.get("currency", "EUR")
    timezone_name = timezone_name if timezone_name is not None else preferences.get("timezone", "Europe/Berlin")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return []
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        return []  # Invalid preferences never silently spend against another zone.
    today = now.astimezone(zone).date()
    local_hour = now.astimezone(zone).hour
    triggers = [("changed_import", latest_import_id, today.replace(day=1), today)] if import_has_changes(latest_import_summary) else []
    if today.weekday() == 0 and local_hour >= 9:
        end = today - timedelta(days=1)
        triggers.append(("weekly", today.isoformat(), end - timedelta(days=6), end))
    if today.day == 1 and local_hour >= 9:
        end = today - timedelta(days=1)
        triggers.append(("monthly", today.strftime("%Y-%m"), end.replace(day=1), end))
    jobs = []
    for channel, key, start, end in triggers:
        if money(policy.channel_limits.get(channel, "0")) <= 0:
            continue
        job = enqueue_report(session, str(owner_id), ChatRequest(start=start, end=end, currency=currency), channel, channel + ":" + key)
        jobs.append(job.id)
    return jobs


# Default integration follows docs/api-contract.md. The main app already owns the
# canonical findings routes and mounts these paths under /api with global CSRF.
from .auth import current_user
from .db import get_db


def authenticated_owner(user=Depends(current_user)) -> str:
    return str(user.id)


router = create_router(get_db, authenticated_owner, finance_query, include_findings=False)
