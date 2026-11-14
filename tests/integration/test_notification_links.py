import pytest

from app.notifications import dashboard_headers


def test_generic_dashboard_links(monkeypatch):
    monkeypatch.setenv("APP_URL", "https://finance.example.invalid")
    assert dashboard_headers("report_ready")["Click"] == "https://finance.example.invalid/insights"
    assert dashboard_headers("weekly")["Actions"] == "view, Open FinSight, https://finance.example.invalid/imports"


@pytest.mark.parametrize("url", ["", "javascript:alert(1)", "https://synthetic:synthetic-password@example.invalid", "https://example.invalid/?token=TEST-TOKEN", "https://example.invalid/accounts/TEST", "https://example.invalid/#private", "https://example.invalid,Other", "https://example.invalid:99999", "https://example.invalid\r\nTitle:TEST"])
def test_private_or_unsafe_notification_links_omitted(monkeypatch, url):
    monkeypatch.setenv("APP_URL", url)
    assert dashboard_headers("weekly") == {}
