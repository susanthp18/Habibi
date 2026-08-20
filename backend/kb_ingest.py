"""KB indexing: claim jobs, chunk, embed, atomically replace chunks."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

import azure_openai
from kb_chunking import chunk_text

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 512
DEFAULT_OVERLAP = 64


def _stuck_after() -> timedelta:
    import os

    from env_loader import load_env

    load_env()
    raw = (os.getenv("KB_STUCK_JOB_MINUTES") or "15").strip()
    try:
        minutes = max(1, int(raw))
    except ValueError:
        minutes = 15
    return timedelta(minutes=minutes)


def _max_attempts() -> int:
    import os

    from env_loader import load_env

    load_env()
    raw = (os.getenv("KB_INDEX_MAX_ATTEMPTS") or "5").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def enqueue_index_job(
    conn: Connection,
    *,
    document_id: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    embedding_model: str | None = None,
    job_id: str | None = None,
) -> str:
    jid = job_id or f"kb-job-{uuid.uuid4().hex[:12]}"
    model = embedding_model or azure_openai.get_embedding_deployment()
    conn.execute(
        text(
            """
            INSERT INTO kb_index_jobs (
              id, document_id, status, chunk_size, chunk_overlap, embedding_model,
              started_at, completed_at, error, created_at, updated_at
            ) VALUES (
              :id, :document_id, 'queued', :chunk_size, :chunk_overlap, :embedding_model,
              NULL, NULL, NULL, now(), now()
            )
            """
        ),
        {
            "id": jid,
            "document_id": document_id,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "embedding_model": model,
        },
    )
    conn.execute(
        text(
            """
            UPDATE kb_documents
            SET status = 'indexing', updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": document_id},
    )
    return jid


def reclaim_stuck_jobs(conn: Connection, *, older_than: timedelta | None = None) -> int:
    """Re-queue jobs stuck in ``running`` past the staleness window.

    Bounded by ``attempt``: a job that keeps dying mid-run (poison document,
    OOM, repeated worker crash) is dead-lettered at ``KB_INDEX_MAX_ATTEMPTS``
    instead of cycling forever. The cutoff is computed database-side so a
    worker with a skewed clock cannot reclaim jobs that are still healthy, and
    the marker text is written once rather than appended on every pass.
    """
    window = older_than or _stuck_after()
    result = conn.execute(
        text(
            """
            UPDATE kb_index_jobs
            SET status = CASE WHEN attempt + 1 >= :cap THEN 'dead' ELSE 'queued' END,
                attempt = attempt + 1,
                error = CASE
                          WHEN attempt + 1 >= :cap THEN 'dead-lettered: stuck running'
                          ELSE 'requeued: stuck running'
                        END,
                completed_at = CASE WHEN attempt + 1 >= :cap THEN now() ELSE NULL END,
                updated_at = now(),
                started_at = NULL
            WHERE status = 'running'
              AND updated_at < now() - CAST(:window AS interval)
            """
        ),
        {"window": f"{int(window.total_seconds())} seconds", "cap": _max_attempts()},
    )
    return result.rowcount or 0


def job_statuses(conn: Connection, job_ids: list[str]) -> dict[str, str]:
    """Terminal/current status per job id — callers gate follow-up work on this."""
    if not job_ids:
        return {}
    rows = conn.execute(
        text("SELECT id, status FROM kb_index_jobs WHERE id = ANY(CAST(:ids AS text[]))"),
        {"ids": list(job_ids)},
    ).mappings().all()
    return {str(r["id"]): str(r["status"]) for r in rows}


def claim_next_job(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, document_id, chunk_size, chunk_overlap, embedding_model
            FROM kb_index_jobs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
    ).fetchone()
    if row is None:
        return None
    job = dict(row._mapping)
    conn.execute(
        text(
            """
            UPDATE kb_index_jobs
            SET status = 'running', started_at = now(), updated_at = now(), error = NULL
            WHERE id = :id
            """
        ),
        {"id": job["id"]},
    )
    return job


def set_document_enabled(conn: Connection, document_id: str, enabled: bool) -> str | None:
    """Disable removes searchable chunks (partial HNSW safety). Re-enable enqueues reindex.

    Returns job_id when a reindex was enqueued; None on disable.
    """
    if not enabled:
        conn.execute(
            text(
                """
                UPDATE kb_documents
                SET enabled = false, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": document_id},
        )
        conn.execute(text("DELETE FROM kb_chunks WHERE document_id = :id"), {"id": document_id})
        return None

    conn.execute(
        text(
            """
            UPDATE kb_documents
            SET enabled = true, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": document_id},
    )
    return enqueue_index_job(conn, document_id=document_id)


def _decode_source_bytes(data: bytes, *, filename: str, mime_type: str | None = None) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Unsupported binary source for indexing ({filename}); use .md/.txt for PoC"
        ) from exc


def _load_source_text(conn: Connection, document_id: str) -> str:
    """Prefer latest MinIO kb_source_files row; fall back to disk source_path (KB-0 bootstrap)."""
    file_row = conn.execute(
        text(
            """
            SELECT storage_ref, filename, mime_type
            FROM kb_source_files
            WHERE document_id = :id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"id": document_id},
    ).fetchone()
    if file_row is not None:
        import storage as object_store

        mapping = file_row._mapping
        data = object_store.get_bytes(mapping["storage_ref"])
        return _decode_source_bytes(
            data,
            filename=mapping["filename"] or "source.txt",
            mime_type=mapping["mime_type"],
        )

    row = conn.execute(
        text("SELECT source_path FROM kb_documents WHERE id = :id"),
        {"id": document_id},
    ).fetchone()
    if row is None:
        raise KeyError(f"document not found: {document_id}")
    source_path = row._mapping["source_path"]
    if not source_path:
        raise ValueError(f"document {document_id} has no source_path and no kb_source_files")
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"source_path missing for {document_id}: {path}")
    return path.read_text(encoding="utf-8")


def _prepare_embedded_chunks(
    conn: Connection,
    job: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, int, str, str]:
    """Load source, chunk, embed. Does not mutate kb_chunks.

    Returns (chunk_rows, chunk_size, overlap, model, content_hash).
    """
    document_id = job["document_id"]
    raw_text = _load_source_text(conn, document_id)
    content_hash = content_sha256(raw_text.encode("utf-8"))
    doc = conn.execute(
        text(
            """
            SELECT chunk_size, chunk_overlap, title, status, embedding_model, content_hash
            FROM kb_documents WHERE id = :id
            """
        ),
        {"id": document_id},
    ).fetchone()
    if doc is None:
        raise KeyError(f"document not found: {document_id}")

    chunk_size = int(job.get("chunk_size") or doc._mapping["chunk_size"] or DEFAULT_CHUNK_SIZE)
    overlap = int(job.get("chunk_overlap") or doc._mapping["chunk_overlap"] or DEFAULT_OVERLAP)
    model = job.get("embedding_model") or azure_openai.get_embedding_deployment()
    prev_hash = doc._mapping.get("content_hash")
    prev_model = doc._mapping.get("embedding_model")
    chunk_count = conn.execute(
        text("SELECT count(*)::int AS n FROM kb_chunks WHERE document_id = :id"),
        {"id": document_id},
    ).scalar() or 0

    # No-op skip: same content + chunk params + model and already indexed.
    if (
        doc._mapping.get("status") == "indexed"
        and prev_hash
        and prev_hash == content_hash
        and int(doc._mapping.get("chunk_size") or 0) == chunk_size
        and int(doc._mapping.get("chunk_overlap") or 0) == overlap
        and prev_model == model
        and int(chunk_count) > 0
    ):
        logger.info(
            "kb_index_skip_unchanged job=%s doc=%s hash=%s",
            job["id"],
            document_id,
            content_hash[:12],
        )
        return [], chunk_size, overlap, model, content_hash

    heading = doc._mapping["title"] or "Body"
    drafts = chunk_text(
        raw_text,
        chunk_size=chunk_size,
        overlap=overlap,
        default_heading=heading,
    )
    if not drafts:
        raise ValueError("chunker produced zero chunks")

    vectors = azure_openai.embed_texts([d.text for d in drafts])
    if len(vectors) != len(drafts):
        raise RuntimeError("embed_texts returned unexpected length")

    chunk_rows: list[dict[str, Any]] = []
    for draft, vec in zip(drafts, vectors, strict=True):
        chunk_rows.append(
            {
                "id": f"{document_id}-c{draft.index}",
                "document_id": document_id,
                "heading": draft.heading,
                "tokens": draft.tokens,
                "text": draft.text,
                "embedding": _vector_literal(vec),
                "chunk_index": draft.index,
                "hits": 0,
            }
        )
    return chunk_rows, chunk_size, overlap, model, content_hash


def _atomic_replace_chunks(
    conn: Connection,
    *,
    job_id: str,
    document_id: str,
    chunk_rows: list[dict[str, Any]],
    chunk_size: int,
    overlap: int,
    model: str,
    content_hash: str,
) -> None:
    """ONE transaction: delete old chunks + insert new + mark indexed/succeeded."""
    if chunk_rows:
        # A set_document_enabled(..., False) that landed while we were embedding
        # must win: re-inserting chunks here would resurrect a disabled doc in
        # ANN results. FOR UPDATE serialises against a concurrent disable.
        still_enabled = conn.execute(
            text("SELECT enabled FROM kb_documents WHERE id = :id FOR UPDATE"),
            {"id": document_id},
        ).scalar()
        if still_enabled is False:
            logger.info(
                "kb_index_discarded_disabled job=%s doc=%s chunks=%s",
                job_id,
                document_id,
                len(chunk_rows),
            )
            chunk_rows = []
    if chunk_rows:
        conn.execute(text("DELETE FROM kb_chunks WHERE document_id = :id"), {"id": document_id})
        for row in chunk_rows:
            conn.execute(
                text(
                    """
                    INSERT INTO kb_chunks (
                      id, document_id, heading, tokens, text, embedding, hits,
                      chunk_index, created_at, updated_at
                    ) VALUES (
                      :id, :document_id, :heading, :tokens, :text, CAST(:embedding AS vector),
                      :hits, :chunk_index, now(), now()
                    )
                    """
                ),
                row,
            )
    # `enabled` is deliberately NOT forced true here — indexing must not
    # re-enable a document an operator disabled mid-flight.
    conn.execute(
        text(
            """
            UPDATE kb_documents
            SET status = 'indexed',
                chunk_size = :chunk_size,
                chunk_overlap = :overlap,
                embedding_model = :model,
                content_hash = :content_hash,
                last_indexed_at = now(),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": document_id,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "model": model,
            "content_hash": content_hash,
        },
    )
    conn.execute(
        text(
            """
            UPDATE kb_index_jobs
            SET status = 'succeeded', completed_at = now(), updated_at = now(),
                chunk_size = :chunk_size, chunk_overlap = :overlap,
                embedding_model = :model, error = NULL
            WHERE id = :id
            """
        ),
        {
            "id": job_id,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "model": model,
        },
    )


def _mark_job_failed(conn: Connection, job_id: str, document_id: str, error: str) -> None:
    """Record job failure without wiping a previously good index.

    Documents that already have ``indexed`` status keep serving last-good
    chunks; only never-indexed docs move to ``failed``.
    """
    conn.execute(
        text(
            """
            UPDATE kb_index_jobs
            SET status = 'failed', completed_at = now(), updated_at = now(), error = :error
            WHERE id = :id
            """
        ),
        {"id": job_id, "error": error[:2000]},
    )
    # A doc mid-reindex sits at status='indexing' (enqueue_index_job) even when
    # it still has a full, serviceable chunk set. Flipping it to 'failed' would
    # drop it out of kb_retrieve's `status = 'indexed'` filter and silently
    # blank the KB for that document. Keep the old status whenever chunks
    # remain; only never-successfully-indexed docs move to 'failed'.
    conn.execute(
        text(
            """
            UPDATE kb_documents
            SET status = CASE
                  WHEN EXISTS (SELECT 1 FROM kb_chunks WHERE document_id = :id) THEN status
                  ELSE 'failed' END,
                updated_at = now()
            WHERE id = :id
              AND status NOT IN ('indexed', 'stale')
            """
        ),
        {"id": document_id},
    )
    # Intentionally do NOT delete existing chunks on failure.


def process_one(engine: Engine) -> bool:
    """Claim → embed (no DELETE yet) → atomic replace. Returns True if a job was claimed."""
    with engine.begin() as conn:
        reclaim_stuck_jobs(conn)
        job = claim_next_job(conn)
    if job is None:
        return False

    job_id = job["id"]
    document_id = job["document_id"]
    try:
        with engine.connect() as conn:
            chunk_rows, chunk_size, overlap, model, content_hash = _prepare_embedded_chunks(conn, job)
        with engine.begin() as conn:
            _atomic_replace_chunks(
                conn,
                job_id=job_id,
                document_id=document_id,
                chunk_rows=chunk_rows,
                chunk_size=chunk_size,
                overlap=overlap,
                model=model,
                content_hash=content_hash,
            )
        logger.info(
            "kb_index_succeeded job=%s doc=%s chunks=%s skipped=%s",
            job_id,
            document_id,
            len(chunk_rows),
            len(chunk_rows) == 0,
        )
    except Exception as exc:
        logger.exception("kb_index_failed job=%s doc=%s", job_id, document_id)
        with engine.begin() as conn:
            _mark_job_failed(conn, job_id, document_id, str(exc))
    return True


def drain_queue(engine: Engine, *, max_jobs: int | None = None) -> int:
    done = 0
    while max_jobs is None or done < max_jobs:
        if not process_one(engine):
            break
        done += 1
    return done


def upsert_document(
    conn: Connection,
    *,
    doc_id: str,
    title: str,
    doc_type: str,
    product_key: str,
    source_path: str,
    version: str = "v1.0",
    tags: list[str] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_OVERLAP,
    # Default is None: production writes must not inherit a seed user identity.
    # Seed scripts pass their own value explicitly.
    updated_by_user_id: str | None = None,
) -> None:
    import db

    tags = tags or [product_key, doc_type]
    conn.execute(
        text(
            """
            INSERT INTO kb_documents (
              id, tenant_id, updated_by_user_id, type, version, status, enabled,
              chunk_size, chunk_overlap, title, tags, embedding_model,
              product_key, source_path, created_at, updated_at
            ) VALUES (
              :id, :tenant_id, :updated_by_user_id, :type, :version, 'draft', true,
              :chunk_size, :chunk_overlap, :title, CAST(:tags AS jsonb), NULL,
              :product_key, :source_path, now(), now()
            )
            ON CONFLICT (id) DO UPDATE SET
              title = EXCLUDED.title,
              type = EXCLUDED.type,
              version = EXCLUDED.version,
              chunk_size = EXCLUDED.chunk_size,
              chunk_overlap = EXCLUDED.chunk_overlap,
              tags = EXCLUDED.tags,
              product_key = EXCLUDED.product_key,
              source_path = EXCLUDED.source_path,
              updated_by_user_id = COALESCE(
                EXCLUDED.updated_by_user_id, kb_documents.updated_by_user_id
              ),
              updated_at = now()
            """
        ),
        {
            "id": doc_id,
            "tenant_id": db.current_tenant(),
            "updated_by_user_id": updated_by_user_id,
            "type": doc_type,
            "version": version,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "title": title,
            "tags": json.dumps(tags),
            "product_key": product_key,
            "source_path": source_path,
        },
    )
