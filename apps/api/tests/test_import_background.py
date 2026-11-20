"""Background imports: the upload returns at once, the import finishes afterwards, failures and stale runs are visible."""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Import, User
from conftest import booking, xlsx


def post(client, data, **form):
    return client.post("/api/imports", files={"file": ("bg.xlsx", data)}, data={k: str(v).lower() for k, v in form.items()})


def listing(owner):
    return {i["filename"]: i for i in owner.get("/api/imports").json()}


def test_background_upload_returns_202_and_completes(owner):
    data = xlsx([booking("a"), booking("b", "-7,25")])
    response = post(owner, data, background=True, full_snapshot=True)
    assert response.status_code == 202 and response.json()["background"] is True and response.json()["status"] == "processing"
    done = listing(owner)["bg.xlsx"]
    assert done["status"] == "completed" and done["summary"]["added"] == 2 and done["row_count"] == 2
    assert len(owner.get("/api/transactions").json()["items"]) == 2


def test_identical_completed_upload_is_a_duplicate_not_a_new_job(owner):
    data = xlsx([booking("a")])
    assert post(owner, data, background=True).status_code == 202
    again = post(owner, data, background=True)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert len(owner.get("/api/imports").json()) == 1


def test_failed_background_import_is_reported(owner):
    bad = xlsx([booking(amount="not-a-number")])
    assert post(owner, bad, background=True).status_code == 202
    failed = listing(owner)["bg.xlsx"]
    assert failed["status"] == "failed" and failed["summary"]["error"]
    assert owner.get("/api/transactions").json()["items"] == []


def test_running_import_of_the_same_file_is_not_started_twice(owner, db):
    data = xlsx([booking("a")])
    uid = db.scalar(select(User.id))
    db.add(Import(user_id=uid, filename="bg.xlsx", sha256=hashlib.sha256(data).hexdigest(), status="processing", row_count=0, summary={}))
    db.commit()
    response = post(owner, data, background=True)
    assert response.status_code == 202
    assert db.scalar(select(Import.status)) == "processing", "no second run was queued"


def test_stale_processing_imports_expire(owner, db):
    uid = db.scalar(select(User.id))
    db.add(Import(user_id=uid, filename="old.xlsx", sha256="a" * 64, status="processing", row_count=0, summary={},
                  created_at=datetime.now(timezone.utc) - timedelta(minutes=45)))
    db.add(Import(user_id=uid, filename="new.xlsx", sha256="b" * 64, status="processing", row_count=0, summary={}))
    db.commit()
    imports = listing(owner)
    assert imports["old.xlsx"]["status"] == "failed" and imports["old.xlsx"]["summary"]["error"] == "Import interrupted"
    assert imports["new.xlsx"]["status"] == "processing"


def test_interrupted_import_resumes_from_retained_upload(owner, db, upload_dir):
    from app import uploads
    from app.routes import resume_interrupted_imports
    data = xlsx([booking("a"), booking("b", "-7,25")])
    digest = hashlib.sha256(data).hexdigest()
    uid = db.scalar(select(User.id))
    # What a crash leaves behind: a 'processing' record, the retained file, no transactions.
    assert uploads.retain(digest, data)
    db.add(Import(user_id=uid, filename="crash.xlsx", sha256=digest, status="processing", row_count=0,
                  summary={"full_snapshot": True, "retained": True}))
    db.commit()
    assert resume_interrupted_imports(db.get_bind()) == 1
    done = listing(owner)["crash.xlsx"]
    assert done["status"] == "completed" and done["summary"]["added"] == 2 and done["summary"]["full_snapshot"] is True
    assert not uploads.exists(digest), "retained file is removed after success"
    assert resume_interrupted_imports(db.get_bind()) == 0, "nothing left to resume; no duplicate transactions"
    assert len(owner.get("/api/transactions").json()["items"]) == 2


def test_failed_import_with_retained_upload_can_be_retried(owner, db, monkeypatch):
    from app import routes, uploads
    data = xlsx([booking("a")])
    real = routes.ingest
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated crash")
        return real(*args, **kwargs)
    monkeypatch.setattr(routes, "ingest", flaky)
    assert post(owner, data, background=True).status_code == 202
    failed = listing(owner)["bg.xlsx"]
    assert failed["status"] == "failed" and failed["summary"]["retry_available"] is True
    assert owner.get("/api/transactions").json()["items"] == []
    retry = owner.post(f"/api/imports/{failed['id']}/retry")
    assert retry.status_code == 202
    again = listing(owner)["bg.xlsx"]
    assert again["status"] == "completed" and not uploads.exists(failed["sha256"] if "sha256" in failed else hashlib.sha256(data).hexdigest())
    assert len(owner.get("/api/transactions").json()["items"]) == 1
    assert owner.post(f"/api/imports/{failed['id']}/retry").status_code == 409, "completed imports cannot be retried"


def test_retention_purges_old_files_and_ignores_bad_names(upload_dir):
    import os
    import time
    from app import uploads
    digest = "a" * 64
    assert uploads.retain(digest, b"x") and uploads.load(digest) == b"x"
    os.utime(upload_dir / f"{digest}.xlsx", (time.time() - 9 * 86400,) * 2)
    assert uploads.purge_old() == 1 and not uploads.exists(digest)
    assert uploads.load("../etc/passwd") is None and uploads.exists("not-a-hash") is False
