"""Per-account coverage report and full-snapshot mode of the watched folder."""
from app.jobs import watch_full_snapshot
from conftest import booking, xlsx


def post(client, data, name="c.xlsx", **form):
    return client.post("/api/imports", files={"file": (name, data)}, data={k: str(v).lower() for k, v in form.items()})


def summary(owner, name):
    return {i["filename"]: i for i in owner.get("/api/imports").json()}[name]["summary"]


def test_coverage_lists_rows_and_period_per_account(owner):
    post(owner, xlsx([booking("a", day="2026-01-05"), booking("b", day="2026-02-10")]), "one.xlsx")
    cov = summary(owner, "one.xlsx")["coverage"]
    assert len(cov) == 1 and cov[0]["rows"] == 2
    assert cov[0]["first"] == "2026-01-05" and cov[0]["last"] == "2026-02-10"
    assert cov[0]["shrunk"] is False and summary(owner, "one.xlsx")["shrunk_accounts"] == []


def test_shrinking_history_is_named(owner):
    post(owner, xlsx([booking("a", day="2026-01-05"), booking("b", day="2026-02-10")]), "old.xlsx", full_snapshot=True)
    post(owner, xlsx([booking("b", day="2026-02-10"), booking("c", day="2026-03-01")]), "new.xlsx", full_snapshot=True)
    s = summary(owner, "new.xlsx")
    assert s["missing"] == 1 and len(s["shrunk_accounts"]) == 1
    cov = s["coverage"][0]
    assert cov["shrunk"] and cov["missing"] == 1 and cov["previous_first"] == "2026-01-05" and cov["previous_rows"] == 2


def test_growing_history_is_not_flagged(owner):
    post(owner, xlsx([booking("b", day="2026-02-10")]), "short.xlsx")
    post(owner, xlsx([booking("a", day="2026-01-05"), booking("b", day="2026-02-10")]), "long.xlsx", full_snapshot=True)
    assert summary(owner, "long.xlsx")["shrunk_accounts"] == []


def test_watcher_snapshot_mode(monkeypatch):
    monkeypatch.delenv("FINSIGHT_WATCH_FULL_SNAPSHOT", raising=False)
    assert watch_full_snapshot("20261119-Export-Alle_Buchungen.xlsx") is True
    assert watch_full_snapshot("Alle Buchungen.xlsx") is True
    assert watch_full_snapshot("Umsaetze-Girokonto.xlsx") is False
    monkeypatch.setenv("FINSIGHT_WATCH_FULL_SNAPSHOT", "false")
    assert watch_full_snapshot("Alle_Buchungen.xlsx") is False
    monkeypatch.setenv("FINSIGHT_WATCH_FULL_SNAPSHOT", "true")
    assert watch_full_snapshot("anything.xlsx") is True
