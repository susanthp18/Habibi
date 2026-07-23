"""MinIO object storage for KB source originals (Phase KB-2).

storage_ref format: minio://{bucket}/kb/{doc_id}/{filename}
(no tenant segment — KB is global for this PoC)
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any
from urllib.parse import unquote, urlparse

from env_loader import load_env

logger = logging.getLogger(__name__)


class StorageConfigError(RuntimeError):
    pass


class StorageUnavailable(RuntimeError):
    pass


def _cfg() -> dict[str, Any]:
    load_env()
    endpoint = (os.getenv("MINIO_ENDPOINT") or "").strip()
    if not endpoint:
        raise StorageConfigError("MINIO_ENDPOINT is not set")
    return {
        "endpoint": endpoint,
        "access_key": (os.getenv("MINIO_ACCESS_KEY") or "minioadmin").strip(),
        "secret_key": (os.getenv("MINIO_SECRET_KEY") or "minioadmin").strip(),
        "bucket": (os.getenv("MINIO_BUCKET") or "collections-kb").strip(),
        "secure": (os.getenv("MINIO_SECURE") or "false").strip().lower() in ("1", "true", "yes"),
    }


def is_configured() -> bool:
    load_env()
    return bool((os.getenv("MINIO_ENDPOINT") or "").strip())


def get_client():
    from minio import Minio

    c = _cfg()
    return Minio(
        c["endpoint"],
        access_key=c["access_key"],
        secret_key=c["secret_key"],
        secure=c["secure"],
    )


def get_bucket() -> str:
    return _cfg()["bucket"]


def ensure_bucket() -> None:
    """Create the KB bucket if missing. No-op when MinIO is not configured."""
    if not is_configured():
        logger.info("minio_skip_ensure reason=not_configured")
        return
    try:
        client = get_client()
        bucket = get_bucket()
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("minio_bucket_created bucket=%s", bucket)
        else:
            logger.info("minio_bucket_ready bucket=%s", bucket)
    except Exception as exc:
        # Do not crash API startup — upload routes will surface unavailability.
        logger.warning("minio_ensure_bucket_failed: %s", exc)


def object_key(doc_id: str, filename: str) -> str:
    safe_name = filename.replace("\\", "/").split("/")[-1] or "upload.bin"
    return f"kb/{doc_id}/{safe_name}"


def make_storage_ref(doc_id: str, filename: str, *, bucket: str | None = None) -> str:
    b = bucket or get_bucket()
    return f"minio://{b}/{object_key(doc_id, filename)}"


def parse_storage_ref(storage_ref: str) -> tuple[str, str]:
    """Return (bucket, object_key) from minio://bucket/key…"""
    if not storage_ref.startswith("minio://"):
        raise ValueError(f"unsupported storage_ref scheme: {storage_ref!r}")
    parsed = urlparse(storage_ref)
    bucket = parsed.netloc
    key = unquote(parsed.path.lstrip("/"))
    if not bucket or not key:
        raise ValueError(f"invalid storage_ref: {storage_ref!r}")
    return bucket, key


def put_bytes(key: str, data: bytes, content_type: str, *, bucket: str | None = None) -> str:
    """Upload bytes; returns storage_ref minio://{bucket}/{key}."""
    if not is_configured():
        raise StorageUnavailable("MinIO is not configured (set MINIO_ENDPOINT)")
    try:
        client = get_client()
        b = bucket or get_bucket()
        if not client.bucket_exists(b):
            client.make_bucket(b)
        client.put_object(
            b,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return f"minio://{b}/{key}"
    except StorageUnavailable:
        raise
    except Exception as exc:
        raise StorageUnavailable(f"minio_put_failed: {exc}") from exc


def get_bytes(storage_ref: str) -> bytes:
    if not is_configured():
        raise StorageUnavailable("MinIO is not configured (set MINIO_ENDPOINT)")
    try:
        client = get_client()
        bucket, key = parse_storage_ref(storage_ref)
        response = client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except StorageUnavailable:
        raise
    except Exception as exc:
        raise StorageUnavailable(f"minio_get_failed: {exc}") from exc


def delete_object(storage_ref: str) -> bool:
    """Best-effort MinIO delete. Returns True if removed; False on skip/failure."""
    if not storage_ref or not storage_ref.startswith("minio://"):
        return False
    if not is_configured():
        return False
    try:
        client = get_client()
        bucket, key = parse_storage_ref(storage_ref)
        client.remove_object(bucket, key)
        return True
    except Exception as exc:
        logger.warning("minio_delete_failed ref=%s err=%s", storage_ref, exc)
        return False
