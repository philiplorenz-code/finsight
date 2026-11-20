from collections import namedtuple

from app import system_status

Usage = namedtuple("Usage", "total used free")


def test_levels(monkeypatch):
    for free, level in ((50, "ok"), (10, "warning"), (3, "critical")):
        monkeypatch.setattr(system_status.shutil, "disk_usage", lambda _p, f=free: Usage(100, 100 - f, f))
        assert system_status.disk_status()["level"] == level


def test_endpoint_requires_login_and_hides_details(client):
    assert client.get("/api/system/disk").status_code in (401, 403)
    client.post("/api/auth/setup", json={"bootstrap_secret": "synthetic-bootstrap-secret",
                                         "email": "synthetic@example.test", "password": "synthetic-long-password"})
    body = client.get("/api/system/disk").json()
    assert set(body) == {"level", "free_percent", "free_gb", "total_gb"}
