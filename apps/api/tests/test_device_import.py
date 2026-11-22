"""Import from the phone with an import-only device key (synthetic data and keys only)."""
from conftest import booking, xlsx


def bearer(value):
    return {"Authorization": f"Bearer {value}"}


def test_device_key_lifecycle_and_upload(owner, client):
    created = owner.post("/api/device-keys", json={"name": "Synthetic iPhone"})
    assert created.status_code == 201
    secret_value = created.json()["key"]
    assert secret_value.startswith("fsd_") and created.json()["upload_url"].endswith("/api/device/import")
    assert "key" not in owner.get("/api/device-keys").json()[0]
    headers = bearer(secret_value)
    # no cookie and no CSRF header needed, only the device key
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    files = {"file": ("export.xlsx", xlsx([booking("d1", "-5")]))}
    r = client.post("/api/device/import", files=files, headers=headers)
    assert r.status_code == 202 and r.json()["filename"] == "export.xlsx"
    assert client.post("/api/device/import", files=files).status_code == 401
    assert client.post("/api/device/import", files={"file": ("x.xlsx", b"synthetic not a zip")}, headers=headers).status_code == 415
    assert client.post("/api/device/import", files=files, headers=bearer("fsd_" + "synthetic-wrong")).status_code == 401
    # the key cannot read anything
    assert client.get("/api/transactions", headers=headers).status_code == 401


def test_revoked_key_stops_working(owner, client):
    created = owner.post("/api/device-keys", json={}).json()
    assert owner.delete(f"/api/device-keys/{created['id']}").status_code == 204
    r = client.post("/api/device/import", files={"file": ("e.xlsx", xlsx([booking()]))}, headers=bearer(created["key"]))
    assert r.status_code == 401
