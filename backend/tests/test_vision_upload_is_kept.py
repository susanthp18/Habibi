"""A customer's uploaded receipt or KYC photo is stored, indexed, and expires.

Vision ingest used to read the image, file a request and drop the bytes; a
`document_files` row claimed a MinIO object nobody uploaded. Now the image goes
to the `customer-uploads` bucket first, its row is written in the request's
transaction with the real size and sha256 and a retention stamp, and the
retention sweep deletes the object before the row. Storage is stubbed here.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import text

import db_core
import storage
from agent_core import retention

IMAGE = b"\xff\xd8\xff\xe0 not really a jpeg"


@pytest.fixture
def ingest(db_tx, monkeypatch):
    has = db_tx.execute(
        text(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'document_files' AND column_name = 'retain_until'"
        )
    ).first()
    if not has:
        pytest.skip("document_files retention columns missing — apply sql/79_customer_uploads.sql")
    monkeypatch.setenv("VISION_INGEST_ENABLED", "true")
    import azure_openai

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("azure_down")),
    )
    customer_id = db_tx.execute(
        text(
            "SELECT a.customer_id FROM accounts a JOIN customers c ON c.id = a.customer_id"
            " WHERE c.id <> 'UNKNOWN-CALLER' ORDER BY a.id LIMIT 1"
        )
    ).scalar()
    if customer_id is None:
        pytest.skip("seed has no customer with an account")
    from agent_core.vision import ingest_customer_document

    def _run(**overrides):
        kwargs = {
            "customer_id": customer_id,
            "filename": "upi-receipt.jpg",
            "mime_type": "image/jpeg",
            "identity_verified": True,
            "content": IMAGE,
        }
        return ingest_customer_document(**{**kwargs, **overrides})

    return _run


def _stub_put(monkeypatch) -> list[tuple]:
    puts: list[tuple] = []

    def _put(key, data, content_type, *, bucket=None):
        puts.append((key, data, content_type, bucket))
        return f"minio://{bucket}/{key}"

    monkeypatch.setattr(storage, "put_bytes", _put)
    return puts


def _file_rows(conn, doc_id: str):
    return conn.execute(
        text(
            "SELECT storage_ref, filename, mime_type, size_bytes, hash, tenant_id,"
            " retention_class, retain_until, created_at"
            " FROM document_files WHERE request_id = :id"
        ),
        {"id": doc_id},
    ).mappings().all()


def test_the_upload_is_stored_then_indexed(db_tx, ingest, monkeypatch) -> None:
    puts = _stub_put(monkeypatch)

    result = ingest()

    assert result.ok, result.error
    [(key, data, mime, bucket)] = puts
    assert bucket == storage.CUSTOMER_UPLOADS_BUCKET
    assert key.startswith(f"{db_core._tenant()}/") and key.endswith(".jpg")
    assert data == IMAGE and mime == "image/jpeg"
    [row] = _file_rows(db_tx, result.data["documentRequestId"])
    assert row["storage_ref"] == f"minio://{bucket}/{key}"
    assert (row["filename"], row["mime_type"]) == ("upi-receipt.jpg", "image/jpeg")
    assert row["size_bytes"] == len(IMAGE)
    assert row["hash"] == hashlib.sha256(IMAGE).hexdigest()
    assert row["tenant_id"] == db_core._tenant()
    assert row["retention_class"] == retention.IDENTIFIED
    assert row["retain_until"] - row["created_at"] == timedelta(days=365)


def test_no_storage_means_no_request_and_no_row(db_tx, ingest, monkeypatch) -> None:
    def _down(*_a, **_k):
        raise storage.StorageUnavailable("minio_put_failed: down")

    monkeypatch.setattr(storage, "put_bytes", _down)
    before = db_tx.execute(text("SELECT count(*) FROM document_requests")).scalar()

    result = ingest()

    assert (result.ok, result.error) == (False, "storage_unavailable")
    assert db_tx.execute(text("SELECT count(*) FROM document_requests")).scalar() == before


def test_a_failed_write_deletes_the_stored_object(db_tx, ingest, monkeypatch) -> None:
    puts = _stub_put(monkeypatch)
    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda ref: deleted.append(ref) or True)

    def _fail(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("db.create_document_request", _fail)

    result = ingest()

    assert (result.ok, result.error) == (False, "crm_write_failed")
    [(key, *_rest, bucket)] = puts
    assert deleted == [f"minio://{bucket}/{key}"]


@pytest.mark.parametrize(
    "overrides,error",
    [({"identity_verified": False}, "identity_not_verified"), ({"content": b""}, "empty_upload")],
)
def test_nothing_is_stored_before_the_gates_pass(ingest, monkeypatch, overrides, error) -> None:
    puts = _stub_put(monkeypatch)
    result = ingest(**overrides)
    assert (result.ok, result.error) == (False, error)
    assert puts == []


def test_the_sweep_deletes_the_object_before_the_row(db_tx, ingest, monkeypatch) -> None:
    _stub_put(monkeypatch)
    doc_id = ingest().data["documentRequestId"]
    # now() is frozen at the fixture's transaction start: back-date, don't wait.
    db_tx.execute(
        text("UPDATE document_files SET retain_until = now() - interval '1 day' WHERE request_id = :id"),
        {"id": doc_id},
    )
    [row] = _file_rows(db_tx, doc_id)

    monkeypatch.setattr(storage, "delete_object", lambda _ref: False)
    retention.sweep(db_tx, tenant_id=db_core._tenant(), record_kind="customer_upload")
    assert len(_file_rows(db_tx, doc_id)) == 1, "row dropped while its object is still stored"

    deleted: list[str] = []
    monkeypatch.setattr(storage, "delete_object", lambda ref: deleted.append(ref) or True)
    retention.sweep(db_tx, tenant_id=db_core._tenant(), record_kind="customer_upload")
    assert deleted == [row["storage_ref"]]
    assert _file_rows(db_tx, doc_id) == []
