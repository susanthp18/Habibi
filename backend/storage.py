"""MinIO object storage for KB source originals (Phase KB-2).

storage_ref format: minio://{bucket}/kb/{doc_id}/{filename}
(no tenant segment — KB is global for this PoC)
"""

from __future__ import annotations

import io
import ipaddress
import logging
import os
import threading
from typing import Any
from urllib.parse import unquote, urlparse

from env_loader import load_env

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_cached_client: Any | None = None
_cached_cfg_key: tuple[str, str, str, bool] | None = None


class StorageConfigError(RuntimeError):
    pass


class StorageUnavailable(RuntimeError):
    pass


def _cfg() -> dict[str, Any]:
    load_env()
    endpoint = (os.getenv("MINIO_ENDPOINT") or "").strip()
    if not endpoint:
        raise StorageConfigError("MINIO_ENDPOINT is not set")
    access = (os.getenv("MINIO_ACCESS_KEY") or "").strip()
    secret = (os.getenv("MINIO_SECRET_KEY") or "").strip()
    # The dev fallback is gated on the *endpoint*, not APP_ENV. A staging box
    # with APP_ENV=dev pointed at a shared MinIO used to fall back to
    # minioadmin/minioadmin and talk plaintext to it — credentials nobody
    # chose, on a host that is not the developer's laptop.
    loopback = _is_loopback_endpoint(endpoint)
    is_prod = (os.getenv("APP_ENV") or "dev").strip().lower() in {"prod", "production"}
    if not access or not secret:
        if is_prod:
            raise StorageConfigError(
                "MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required in production"
            )
        if not loopback:
            raise StorageConfigError(
                "MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required for a "
                f"non-loopback endpoint ({endpoint})"
            )
        logger.warning("MinIO credentials unset — using local defaults (loopback endpoint only)")
        access = access or "minioadmin"
        secret = secret or "minioadmin"
    raw_secure = (os.getenv("MINIO_SECURE") or "").strip().lower()
    if raw_secure:
        secure = raw_secure in ("1", "true", "yes")
    else:
        # Default to TLS for anything off the loopback; plaintext stays the
        # default only for the local docker-compose MinIO.
        secure = not loopback
    return {
        "endpoint": endpoint,
        "access_key": access,
        "secret_key": secret,
        "bucket": (os.getenv("MINIO_BUCKET") or "collections-kb").strip(),
        "secure": secure,
    }


def _is_loopback_endpoint(endpoint: str) -> bool:
    """True when MINIO_ENDPOINT points at this machine.

    ``MINIO_ENDPOINT`` is a bare ``host:port`` (no scheme) for the MinIO SDK, so
    parse it as an authority. Anything unparseable is treated as remote — the
    conservative direction.
    """
    host = endpoint.split("//")[-1].split("/")[0]
    if host.startswith("["):  # bracketed IPv6
        host = host[1 : host.find("]")] if "]" in host else host[1:]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    host = host.strip().lower()
    if host in {"localhost", "minio"}:
        # "minio" is the docker-compose service name on the app's own network.
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_configured() -> bool:
    load_env()
    return bool((os.getenv("MINIO_ENDPOINT") or "").strip())


def get_client():
    """Memoized Minio client — one instance per process for matching credentials."""
    global _cached_client, _cached_cfg_key
    from minio import Minio

    c = _cfg()
    key = (c["endpoint"], c["access_key"], c["secret_key"], bool(c["secure"]))
    with _client_lock:
        if _cached_client is not None and _cached_cfg_key == key:
            return _cached_client
        _cached_client = Minio(
            c["endpoint"],
            access_key=c["access_key"],
            secret_key=c["secret_key"],
            secure=c["secure"],
        )
        _cached_cfg_key = key
        return _cached_client


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


def ping() -> dict[str, Any]:
    """Non-mutating readiness probe. Returns {ok, configured, detail?}."""
    if not is_configured():
        return {"ok": True, "configured": False, "detail": "not_configured"}
    try:
        client = get_client()
        bucket = get_bucket()
        exists = bool(client.bucket_exists(bucket))
        if not exists:
            return {"ok": False, "configured": True, "detail": f"bucket_missing:{bucket}"}
        return {"ok": True, "configured": True, "bucket": bucket}
    except Exception as exc:
        return {"ok": False, "configured": True, "detail": str(exc)}


def _minio_breaker():
    """Breaker for MinIO, tuned for what is and is not a dependency failure.

    A malformed storage_ref or an unconfigured deployment is a caller/config
    problem — counting those would trip the breaker and fail healthy traffic.
    """
    import circuit_breaker

    return circuit_breaker.get_breaker(
        "minio",
        ignore_exceptions=(ValueError,),
    )


def object_key(doc_id: str, filename: str) -> str:
    """Build the ``kb/{doc_id}/{name}`` key for an uploaded source file.

    Traversal-safe: separators are stripped and dot-only segments ("." / "..",
    which survive the split and would let a ref resolve outside the document
    prefix once ``parse_storage_ref`` unquotes it) are rejected. Both components
    are sanitised — doc_id can be caller-supplied via upsert_document, so
    sanitising only the filename still left ``kb/../../<name>`` reachable.
    """
    safe_id = _safe_segment(doc_id, fallback="")
    if not safe_id:
        raise ValueError(f"invalid doc_id for object key: {doc_id!r}")
    safe_name = _safe_segment(filename, fallback="upload.bin")
    return f"kb/{safe_id}/{safe_name}"


def _safe_segment(raw: str | None, *, fallback: str) -> str:
    """One path segment with separators and dot-only names removed."""
    value = unquote(raw or "").replace("\\", "/").split("/")[-1].strip()
    if not value or set(value) == {"."}:
        return fallback
    return value


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
    # Configuration is checked outside the breaker for the same reason
    # ValueError is ignored inside it: an unconfigured deployment is a config
    # problem, and counting it as a dependency failure trips the breaker
    # against a MinIO that was never contacted.
    _require_configured()
    return _minio_breaker().call(
        _put_bytes_uncircuited, key, data, content_type, bucket=bucket
    )


def _require_configured() -> None:
    if not is_configured():
        raise StorageUnavailable("MinIO is not configured (set MINIO_ENDPOINT)")


def _put_bytes_uncircuited(
    key: str, data: bytes, content_type: str, *, bucket: str | None = None
) -> str:
    if not is_configured():
        raise StorageUnavailable("MinIO is not configured (set MINIO_ENDPOINT)")
    try:
        client = get_client()
        b = bucket or get_bucket()
        # Bucket provisioning is owned by ensure_bucket(); do not create here.
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
    _require_configured()
    return _minio_breaker().call(_get_bytes_uncircuited, storage_ref)


def _get_bytes_uncircuited(storage_ref: str) -> bytes:
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
