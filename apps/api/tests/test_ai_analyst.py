"""AI analyst with a local fake provider: no network, no real data."""
import asyncio
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import app.ai_analyst as analyst
from app.ai import AIBlocked, AIPolicy, AIRun
from app.models import Finding, User
from app.wishlist import baseline
from conftest import booking, upload
from test_wishlist import workbook


def enable(db, user_id, **kwargs):
    values = dict(owner_id=user_id, enabled=True, external_consent=True, proactive_consent=False, model="synthetic/model",
                  prices={"synthetic/model": {"input": "1", "output": "2", "currency": "EUR", "verified": True}},
                  total_limit=Decimal("5"), monthly_limit=Decimal("5"), run_limit=Decimal("1"), budget_currency="EUR",
                  channel_limits={"chat": "5"}, max_concurrent=2, max_input_tokens=8000, max_output_tokens=800,
                  max_steps=3, max_tools=1, timeout_seconds=5)
    values.update(kwargs)
    row = AIPolicy(**values)
    db.add(row)
    db.commit()
    return row


class Fake:
    def __init__(self, answer="Kurzantwort: ok.", usage=None):
        self.calls, self.answer = [], answer
        self.usage = {"prompt_tokens": 1200, "completion_tokens": 80} if usage is None else usage

    async def __call__(self, model, messages, max_tokens, timeout, **kwargs):
        self.calls.append({"model": model, "messages": messages})
        return self.answer, self.usage


def seed(owner, db):
    workbook(owner, [booking("shop", "-100", day="2026-03-10", **{"Kategorie": "Einkaufen", "Empfänger": "Geheimer Laden"})])
    assert owner.post("/api/income-rules", json={"name": "B", "source": "employment", "pattern": "synthetic"}).status_code == 201
    return db.scalar(select(User.id))


def test_context_is_aggregated_rounded_and_has_no_names_by_default(owner, db):
    uid = seed(owner, db)
    owner.post("/api/wishes", json={"name": "Privates Wunsch", "price": "999.49", "priority": 1})
    ctx = analyst.build_context(db, uid)
    text = json.dumps(ctx, ensure_ascii=False)
    assert "Geheimer Laden" not in text and "Privates Wunsch" not in text and "Synthetic shop" not in text
    assert ctx["currency"] == "EUR" and ctx["months_analyzed"] == 6
    assert ctx["monthly_averages"]["income"] == 3000 and isinstance(ctx["monthly_averages"]["income"], int)
    assert ctx["open_wishes"][0]["price"] == 999 and "name" not in ctx["open_wishes"][0]
    assert {"recent_months", "spending_categories", "recurring_contracts", "net_worth", "data_quality"} <= set(ctx)
    assert len(ctx["recent_months"]) <= 12 and all(set(r) == {"month", "income", "private_spending", "business_spending", "surplus"} for r in ctx["recent_months"])
    with_names = analyst.build_context(db, uid, include_names=True)
    assert with_names["open_wishes"][0]["name"] == "Privates Wunsch"


def test_names_are_cleaned_and_bounded():
    assert analyst.clean("a\nb\x00c   d" + "x" * 100, 10) == "a b c dxxx"
    assert analyst.euro(None) == 0 and analyst.euro("999.49") == 999 and analyst.euro("999.5") in (999, 1000)


def test_ask_charges_the_budget_stores_a_finding_and_returns_what_was_sent(owner, db):
    uid = seed(owner, db)
    enable(db, uid)
    fake = Fake()
    result = asyncio.run(analyst.execute_ask(db, uid, analyst.AskRequest(question="Wo kann ich sparen?"), provider=fake))
    assert result["answer"] == "Kurzantwort: ok." and result["sent"]["currency"] == "EUR"
    sent = fake.calls[0]["messages"]
    assert sent[0]["role"] == "system" and "keine Anlage" in sent[0]["content"]
    assert "Wo kann ich sparen?" in sent[1]["content"] and "Geheimer Laden" not in sent[1]["content"]
    run = db.scalar(select(AIRun))
    assert run.state == "settled" and run.input_tokens == 1200 and run.charged == Decimal("1200") / 10**6 * 1 + Decimal("80") / 10**6 * 2
    assert db.scalar(select(Finding).where(Finding.kind == "ai")).body == "Kurzantwort: ok."


def test_ask_is_blocked_without_consent_and_sends_nothing(owner, db):
    uid = seed(owner, db)
    fake = Fake()
    with pytest.raises(AIBlocked, match="external_ai_disabled"):
        asyncio.run(analyst.execute_ask(db, uid, analyst.AskRequest(question="Hallo Welt"), provider=fake))
    enable(db, uid, enabled=True, external_consent=False)
    with pytest.raises(AIBlocked, match="external_ai_disabled"):
        asyncio.run(analyst.execute_ask(db, uid, analyst.AskRequest(question="Hallo Welt"), provider=fake))
    assert fake.calls == []


def test_unverified_usage_keeps_liability_and_empty_answers_are_rejected(owner, db):
    uid = seed(owner, db)
    enable(db, uid)
    with pytest.raises(AIBlocked, match="provider_usage_unverified"):
        asyncio.run(analyst.execute_ask(db, uid, analyst.AskRequest(question="Hallo Welt"), provider=Fake(usage={})))
    assert db.scalar(select(AIRun)).state == "uncertain"
    with pytest.raises(AIBlocked, match="output_limit"):
        asyncio.run(analyst.execute_ask(db, uid, analyst.AskRequest(question="Nochmal"), provider=Fake(answer="  ")))


def test_endpoint_preview_and_ask_with_fake_provider(owner, db, monkeypatch):
    uid = seed(owner, db)
    preview = owner.get("/api/ai/context").json()
    assert preview["context"]["months_analyzed"] == 6 and "Finanzanalyst" in preview["system_prompt"]
    assert owner.get("/api/ai/context?currency=eur").status_code == 422
    assert owner.post("/api/ai/ask", json={"question": "x"}).status_code == 422, "too short"
    assert owner.post("/api/ai/ask", json={"question": "Hallo Welt", "bogus": 1}).status_code == 422
    assert owner.post("/api/ai/ask", json={"question": "Hallo Welt"}).status_code == 409, "no consent configured"
    enable(db, uid)
    monkeypatch.setitem(analyst.PROVIDER, "call", Fake())
    ok = owner.post("/api/ai/ask", json={"question": "Wo kann ich sparen?"})
    assert ok.status_code == 200 and ok.json()["answer"] and ok.json()["sent"]["currency"] == "EUR"


def test_requires_login(client):
    assert client.get("/api/ai/context").status_code in {401, 403}
    assert client.post("/api/ai/ask", json={"question": "Hallo Welt"}).status_code in {401, 403}


def test_plan_selects_sections_by_topic():
    debt = analyst.plan_for("Wann ist mein Kredit abbezahlt?")
    assert debt["topics"] == ["debt"] and "net_worth" in debt["sections"] and "spending_categories" not in debt["sections"]
    mixed = analyst.plan_for("Kann ich mir ein Auto leisten und wo kann ich sparen?")
    assert {"wishes", "savings"} <= set(mixed["topics"]) and {"open_wishes", "spending_categories"} <= mixed["sections"]
    general = analyst.plan_for("Was fällt dir auf?")
    assert general == {"topics": ["general"], "sections": None}
    ctx = {"currency": "EUR", "net_worth": {}, "spending_categories": [], "health": {}}
    assert set(analyst.apply_plan(ctx, debt)) == {"currency", "net_worth", "health"}
    assert analyst.apply_plan(ctx, general) == ctx
    assert "_secret_tool_input" not in analyst.apply_plan({**ctx, "_secret_tool_input": 1}, general)


def test_context_endpoint_applies_the_plan_and_includes_health(owner):
    workbook(owner)
    full = owner.get("/api/ai/context").json()
    assert "health" in full["context"] and "payoff_scenarios" in full["context"] and full["topics"] == ["general"]
    small = owner.get("/api/ai/context", params={"question": "Wie hoch ist mein Kredit?"}).json()
    assert small["topics"] == ["debt"] and "spending_categories" not in small["context"] and "net_worth" in small["context"]
    assert "alerts" in full["context"]["health"] and all(set(a) == {"code", "severity"} for a in full["context"]["health"]["alerts"])


def test_structured_findings_are_ranked_and_evidenced(owner):
    rows = []
    for month in range(1, 7):
        rows.append(booking(f"in-{month}", "3000", day=f"2026-{month:02d}-01"))
        rows.append(booking(f"out-{month}", "-3500", day=f"2026-{month:02d}-15", **({"Kontostand": "1000"} if month == 6 else {})))
    assert upload(owner, rows).status_code == 200
    account = owner.get("/api/accounts").json()[0]
    owner.patch(f"/api/accounts/{account['id']}", json={"ownership": "owned"})
    found = owner.get("/api/ai/findings").json()
    assert found and found[0]["severity"] == "high"
    negative = next(f for f in found if f["code"] == "negative_surplus")
    assert negative["impact_monthly"] == 500 and negative["evidence"]["source"] == "health_metrics"
    assert {"title", "severity", "confidence", "impact_monthly", "evidence"} <= set(negative)
    assert owner.get("/api/ai/findings", params={"currency": "eur"}).status_code == 422


def test_planner_chains_typed_tools_within_the_step_budget():
    ctx = {"confidence": "low", "health": {"unavailable": ["debt_service_ratio"]}, "data_quality": {"accounts_with_gaps_in_window": 1},
           "recurring_contracts": {"running_with_price_increase": 2},
           "spending_categories": [{"category": "Einkaufen", "monthly_typical_earlier": 100, "monthly_typical_recent": 160, "monthly_average": 130, "fixed": False},
                                   {"category": "Miete", "monthly_typical_earlier": 800, "monthly_typical_recent": 900, "monthly_average": 850, "fixed": True}]}
    question = "Wo kann ich bei Einkaufen sparen?"
    extra, trace = analyst.run_planner(question, analyst.plan_for(question), ctx)
    assert [t["tool"] for t in trace] == ["focus_category", "rank_levers", "contract_focus", "data_caveats"] and len(trace) <= analyst.MAX_STEPS
    assert extra["focus_category"]["category"] == "Einkaufen"
    assert extra["ranked_levers"][0] == {"kind": "rising_category", "category": "Einkaufen", "monthly_impact": 60}  # fixed Miete is not a lever
    assert set(extra["caveats"]) == {"low_confidence", "metrics_unavailable:debt_service_ratio", "account_gaps_in_window"}


def test_planner_skips_unneeded_tools_and_rejects_unknown_arguments():
    ctx = {"spending_categories": [], "health": {}, "data_quality": {}}
    extra, trace = analyst.run_planner("Wie hoch ist mein Kredit?", analyst.plan_for("Wie hoch ist mein Kredit?"), ctx)
    assert extra == {} and [t["tool"] for t in trace] == ["focus_category", "data_caveats"] and not any(t["used"] for t in trace)
    with pytest.raises(Exception):
        analyst.TOOLS["rank_levers"][0](sql="select 1")


def test_ask_reports_the_planner_steps(owner, db):
    user_id = seed(owner, db)
    enable(db, user_id)
    result = asyncio.run(analyst.execute_ask(db, user_id, analyst.AskRequest(question="Wo kann ich bei Einkaufen sparen?"), provider=Fake()))
    assert [s["tool"] for s in result["steps"]][0] == "focus_category" and "focus_category" in result["sent"]



def test_contract_and_tax_tools_add_only_their_sections():
    ctx = {"spending_categories": [], "health": {}, "data_quality": {},
           "_contract_details": [{"kind": "insurance", "rhythm": "monthly", "monthly": 129, "price_change_per_charge": 0}],
           "_tax_reserves": {"year": 2026, "vat_contained": 190, "vat_moved_to_pot": 150}}
    q = "Welche Verträge kann ich kündigen?"
    extra, trace = analyst.run_planner(q, analyst.plan_for(q), ctx)
    assert extra["top_contracts"][0]["kind"] == "insurance" and "tax_reserves" not in extra
    q2 = "Wie viel Steuer muss ich fürs Nebengewerbe zurücklegen?"
    extra2, trace2 = analyst.run_planner(q2, analyst.plan_for(q2), ctx)
    assert extra2["tax_reserves"]["vat_moved_to_pot"] == 150 and "top_contracts" not in extra2
    assert all(not k.startswith("_") for k in analyst.apply_plan(ctx, analyst.plan_for(q2)))


def test_year_question_adds_the_year_review_without_merchant_names(owner, db):
    user_id = seed(owner, db)
    question = "Wie war mein Jahr im Vergleich zum Vorjahr?"
    ctx = analyst.build_context(db, user_id)
    review = ctx["_year_review"]
    assert {"this_year", "previous_year_same_period", "category_changes", "months"} <= set(review) and "top_merchants" not in review
    assert all(isinstance(v, int) for v in review["this_year"].values())
    extra, trace = analyst.run_planner(question, analyst.plan_for(question), ctx)
    assert [t["tool"] for t in trace][:2] == ["focus_category", "year_compare"] and extra["year_review"] == review
    assert "top_merchants" in analyst.build_context(db, user_id, include_names=True)["_year_review"]
    # a question without a year never sends it
    other, _ = analyst.run_planner("Wie hoch ist mein Kredit?", analyst.plan_for("Wie hoch ist mein Kredit?"), ctx)
    assert "year_review" not in other
