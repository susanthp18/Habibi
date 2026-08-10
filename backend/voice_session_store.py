"""Cross-process store for Sandbox Live voice session config.

``POST /voice/sandbox/start`` runs in the API process and writes the session
bundle (prompt version, KB snapshot, scenario, persona, tuning); ``voice.bot``
reads it when the browser's WebRTC offer arrives. Those two are the *same*
process only when ``VOICE_EMBEDDED_HOST=true``. In the default deployment they
are separate containers (``collections_api`` and ``collections_voice``) with
separate filesystems, so the original JSON-file store meant the bot could never
see a session the API had written: every Live call silently fell back to the
production bundle with default tuning, and the Tuning Studio / persona / KB
snapshot had no effect at all.

Postgres is the primary backend. It is the one dependency every voice-carrying
process already has (``DATABASE_URL`` + a health-gated ``depends_on`` on all of
api / voice / voice_insurance / worker), it survives a restart, and
``SELECT … FOR UPDATE`` gives read-modify-write atomicity across processes and
hosts — replacing the hand-rolled ``O_EXCL`` lock-file protocol that only ever
worked within one filesystem. This mirrors the choice already made in
:mod:`kb_rate_limit` for the same reason.

The filesystem backend is kept for contexts with no database (unit tests, a
single-process laptop run). It is only selected when Postgres is genuinely
unreachable, and that degradation is logged at ERROR — a split store is exactly
the failure this module exists to prevent, so we never silently fall back
*after* having chosen Postgres.

Backend selection is ``VOICE_SESSION_STORE``: ``auto`` (default), ``postgres``,
or ``file``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Canonical sandbox session id. Also the path-traversal guard for the file
# backend, and the discriminator that keeps a transport-minted connection id
# (``uuid4`` from ``pipecat.runner``) from being mistaken for one of ours.
_SESSION_ID_RE = re.compile(r"^VS-[0-9A-F]{10}$")

_SESSIONS_DIR = Path(__file__).resolve().parent / ".cache" / "voice_sandbox_sessions"

_TABLE = "voice_sandbox_sessions"


class SessionStoreUnavailable(RuntimeError):
    """The chosen backend could not be reached.

    Distinct from "session not found" (``None``) on purpose: a caller that
    cannot tell the two apart reports a *missing* session when the real problem
    is a dead database, which is how the original file store hid a whole broken
    deployment behind a routine-looking warning.
    """


def is_session_id(value: object) -> bool:
    """True when ``value`` is a canonical ``VS-XXXXXXXXXX`` sandbox session id."""
    return bool(_SESSION_ID_RE.fullmatch(value if isinstance(value, str) else ""))


def _require_session_id(session_id: str) -> str:
    if not is_session_id(session_id):
        raise ValueError(f"invalid_session_id: {session_id!r}")
    return session_id


# --------------------------------------------------------------------------
# Backend selection
# --------------------------------------------------------------------------

_backend: str | None = None
_backend_guard = threading.Lock()


def _configured_mode() -> str:
    mode = (os.getenv("VOICE_SESSION_STORE") or "auto").strip().lower()
    return mode if mode in {"auto", "postgres", "file"} else "auto"


def _probe_postgres() -> bool:
    """True when the sessions table is queryable right now."""
    try:
        import db
        from sqlalchemy import text

        with db.engine.connect() as conn:
            conn.execute(text(f"SELECT 1 FROM {_TABLE} LIMIT 1"))
        return True
    except Exception:
        return False


def backend() -> str:
    """The active backend name, resolved once per process."""
    global _backend
    if _backend is not None:
        return _backend
    with _backend_guard:
        if _backend is not None:
            return _backend
        mode = _configured_mode()
        if mode == "file":
            logger.warning(
                "voice session store: file backend forced — Sandbox Live only works "
                "when the API and the voice worker share this filesystem"
            )
            _backend = "file"
        elif mode == "postgres":
            # Explicit opt-in must not silently degrade; a failing probe here is
            # a deployment error the operator asked to be told about.
            if not _probe_postgres():
                raise SessionStoreUnavailable(
                    f"VOICE_SESSION_STORE=postgres but {_TABLE} is not queryable "
                    "(run: alembic upgrade head)"
                )
            _backend = "postgres"
        elif _probe_postgres():
            _backend = "postgres"
        else:
            logger.error(
                "voice session store: %s unreachable — falling back to the local "
                "filesystem. Sandbox Live persona/KB/tuning will not reach the voice "
                "worker unless it shares this filesystem. Run `alembic upgrade head`.",
                _TABLE,
            )
            _backend = "file"
        logger.info("voice session store backend: %s", _backend)
        return _backend


def reset_backend_cache() -> None:
    """Forget the resolved backend. For tests and post-migration re-probe."""
    global _backend
    with _backend_guard:
        _backend = None


# --------------------------------------------------------------------------
# Postgres backend
# --------------------------------------------------------------------------


def _pg_read(session_id: str) -> dict[str, Any] | None:
    import db
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT payload FROM {_TABLE} WHERE id = :id"),
                {"id": session_id},
            ).scalar()
    except Exception as exc:
        raise SessionStoreUnavailable(f"voice session read failed: {exc}") from exc
    if row is None:
        return None
    # psycopg returns jsonb as a dict already; tolerate a driver that hands back
    # text so a connection-level type-adapter change cannot break every call.
    return json.loads(row) if isinstance(row, (str, bytes)) else dict(row)


def _pg_write(session_id: str, payload: dict[str, Any]) -> None:
    import db
    from sqlalchemy import text

    try:
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {_TABLE} (id, payload)
                    VALUES (:id, CAST(:payload AS jsonb))
                    ON CONFLICT (id) DO UPDATE
                      SET payload = EXCLUDED.payload, updated_at = now()
                    """
                ),
                {"id": session_id, "payload": json.dumps(payload)},
            )
    except Exception as exc:
        raise SessionStoreUnavailable(f"voice session write failed: {exc}") from exc


def _pg_mutate(
    session_id: str, fn: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any] | None:
    import db
    from sqlalchemy import text

    # An exception raised by ``fn`` must reach the caller unchanged — reporting a
    # caller's own validation error as a store outage would be a lie, and it
    # aborts the transaction either way.
    from_handler: list[BaseException] = []

    def _apply(current: dict[str, Any]) -> dict[str, Any]:
        try:
            return fn(current)
        except BaseException as exc:  # noqa: BLE001 — re-raised immediately
            from_handler.append(exc)
            raise

    try:
        with db.engine.begin() as conn:
            # FOR UPDATE holds the row for the whole read → merge → write, so two
            # concurrent tunes cannot both read the pre-merge state and have the
            # second write drop the first delta.
            row = conn.execute(
                text(f"SELECT payload FROM {_TABLE} WHERE id = :id FOR UPDATE"),
                {"id": session_id},
            ).scalar()
            if row is None:
                return None
            current = json.loads(row) if isinstance(row, (str, bytes)) else dict(row)
            updated = _apply(current)
            conn.execute(
                text(
                    f"""
                    UPDATE {_TABLE}
                       SET payload = CAST(:payload AS jsonb), updated_at = now()
                     WHERE id = :id
                    """
                ),
                {"id": session_id, "payload": json.dumps(updated)},
            )
            return updated
    except Exception as exc:
        if from_handler and from_handler[0] is exc:
            raise
        raise SessionStoreUnavailable(f"voice session update failed: {exc}") from exc


def _pg_purge(cutoff_seconds: float) -> int:
    import db
    from sqlalchemy import text

    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                DELETE FROM {_TABLE}
                 WHERE updated_at < now() - CAST(:window AS interval)
                """
            ),
            {"window": f"{max(1, int(cutoff_seconds))} seconds"},
        )
    return result.rowcount or 0


# --------------------------------------------------------------------------
# Filesystem backend (no-database fallback)
# --------------------------------------------------------------------------

_LOCK_TIMEOUT_S = 5.0
_LOCK_STALE_S = 30.0


@dataclass
class _LockEntry:
    lock: threading.Lock
    waiters: int


_thread_locks: dict[str, _LockEntry] = {}
_thread_locks_guard = threading.Lock()


def _ensure_dir() -> None:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def session_path(session_id: str) -> Path:
    """Path for a session on the file backend. Rejects non-canonical ids."""
    return _SESSIONS_DIR / f"{_require_session_id(session_id)}.json"


@contextmanager
def _thread_lock(session_id: str) -> Iterator[None]:
    """Hold the per-session in-process lock, dropping the entry once idle.

    Reference counting under the guard means an entry is removed only while no
    thread holds or is waiting for it, so mutual exclusion is unchanged while a
    long-running process stops accumulating one Lock per sandbox run.
    """
    with _thread_locks_guard:
        entry = _thread_locks.get(session_id)
        if entry is None:
            entry = _LockEntry(threading.Lock(), 0)
            _thread_locks[session_id] = entry
        entry.waiters += 1
        lock = entry.lock
    lock.acquire()
    try:
        yield
    finally:
        lock.release()
        with _thread_locks_guard:
            current = _thread_locks.get(session_id)
            if current is entry:
                entry.waiters -= 1
                if entry.waiters <= 0:
                    _thread_locks.pop(session_id, None)


def _read_lock_token(lock_path: Path) -> bytes | None:
    try:
        return lock_path.read_bytes()
    except OSError:
        return None


def _unlink_lock_if_owned(lock_path: Path, token: bytes | None) -> None:
    """Remove the lock file only while it still carries ``token``."""
    if token is None:
        return
    try:
        if lock_path.read_bytes() != token:
            # Someone else holds it now — releasing here would hand a third
            # writer the lock while that holder is mid-write.
            return
        lock_path.unlink()
    except OSError:
        pass


@contextmanager
def _file_lock(session_id: str) -> Iterator[None]:
    """Exclusive lock for one session across the whole read/merge/write."""
    _ensure_dir()
    lock_path = session_path(session_id).with_suffix(".lock")
    # Ownership token: stale-breaking and unconditional unlink together let a
    # process that stalled past _LOCK_STALE_S delete the lock a *different*
    # worker had since acquired. The token makes both the break and the release
    # verify who actually holds it.
    token = f"{os.getpid()}:{uuid.uuid4().hex}".encode()
    with _thread_lock(session_id):
        deadline = time.monotonic() + _LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, token)
                finally:
                    os.close(fd)
                break
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > _LOCK_STALE_S:
                    logger.warning("breaking stale voice sandbox lock %s", lock_path.name)
                    _unlink_lock_if_owned(lock_path, _read_lock_token(lock_path))
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"voice_session_locked: {session_id}")
                time.sleep(0.02)
        try:
            yield
        finally:
            _unlink_lock_if_owned(lock_path, token)


def _file_read(session_id: str) -> dict[str, Any] | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    # A corrupt file *raises*. Swallowing it into None made stop/tune report
    # ``voice_session_not_found``, so a truncated write left a sandbox run that
    # could never be stopped and whose real problem was invisible.
    return json.loads(path.read_text(encoding="utf-8"))


def _file_write(session_id: str, payload: dict[str, Any]) -> None:
    _ensure_dir()
    path = session_path(session_id)
    # Unique temp name: two writers for the same session would otherwise both
    # write the shared "<id>.json.tmp" and one os.replace would move a file the
    # other was still writing.
    tmp = path.with_suffix(f".json.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _file_mutate(
    session_id: str, fn: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any] | None:
    with _file_lock(session_id):
        current = _file_read(session_id)
        if current is None:
            return None
        updated = fn(current)
        _file_write(session_id, updated)
        return updated


def _file_purge(cutoff_seconds: float) -> int:
    if not _SESSIONS_DIR.exists():
        return 0
    cutoff = time.time() - max(1.0, cutoff_seconds)
    removed = 0
    for path in _SESSIONS_DIR.glob("VS-*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def read(session_id: str) -> dict[str, Any] | None:
    """The stored session, or None when no such session exists.

    Raises ``ValueError`` for a malformed id and ``SessionStoreUnavailable``
    when the backend itself is broken — neither is "not found".
    """
    _require_session_id(session_id)
    return _pg_read(session_id) if backend() == "postgres" else _file_read(session_id)


def write(session_id: str, payload: dict[str, Any]) -> None:
    """Create or replace a session."""
    _require_session_id(session_id)
    if backend() == "postgres":
        _pg_write(session_id, payload)
    else:
        _file_write(session_id, payload)


def mutate(
    session_id: str, fn: Callable[[dict[str, Any]], dict[str, Any]]
) -> dict[str, Any] | None:
    """Atomically read-modify-write one session.

    ``fn`` receives the current payload and returns the replacement; it runs
    while the session is held exclusively, so callers can merge safely. Returns
    the new payload, or None when the session does not exist.
    """
    _require_session_id(session_id)
    if backend() == "postgres":
        return _pg_mutate(session_id, fn)
    return _file_mutate(session_id, fn)


def purge_stale(older_than_seconds: float = 24 * 3600) -> int:
    """Drop sessions untouched for ``older_than_seconds``. Never raises."""
    try:
        if backend() == "postgres":
            return _pg_purge(older_than_seconds)
        return _file_purge(older_than_seconds)
    except Exception:
        logger.debug("voice session purge failed", exc_info=True)
        return 0
