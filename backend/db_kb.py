"""Knowledge Base library admin, FAQs and analytics gaps.

Peeled from ``db.py`` (WP-036 peel 9). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge Base (RAG) — Phase KB-2 library admin
# ---------------------------------------------------------------------------

_KB_ALLOWED_TYPES = {"policy", "sop", "product", "compliance", "faq", "benefits"}


def _kb_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except Exception:
            return [value] if value else []
    return []


def _kb_filename_fallback(source_path: str | None, doc_id: str) -> str:
    if source_path:
        return Path(source_path).name
    return f"{doc_id}.txt"


def _bump_kb_version(version: str | None) -> str:
    raw = (version or "v1.0").lstrip("vV")
    parts = raw.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"v{major}.{minor + 1}"
    except ValueError:
        return f"{version or 'v1'}-next"


def _serialize_kb_document(row: dict[str, Any]) -> dict[str, Any]:
    last = row.get("last_indexed_at") or row.get("updated_at") or ""
    chunk_size = int(row.get("chunk_size") or 512)
    overlap = int(row.get("chunk_overlap") or 64)
    return {
        "id": row["id"],
        "title": row.get("title") or row["id"],
        "filename": row.get("filename")
        or _kb_filename_fallback(row.get("source_path"), row["id"]),
        "type": row["type"],
        "version": row.get("version") or "v1.0",
        "status": row.get("status") or "draft",
        "enabled": bool(row.get("enabled")),
        "chunks": int(row.get("chunk_count") or 0),
        "chunkSize": chunk_size,
        "overlap": overlap,
        "embeddingModel": row.get("embedding_model") or "",
        "updatedBy": row.get("updated_by_name") or "System",
        "lastIndexed": last if isinstance(last, str) else (last.isoformat() if last else ""),
        "tags": _kb_tags(row.get("tags")),
    }


_KB_DOC_SELECT = """
    SELECT d.id, d.title, d.type, d.version, d.status, d.enabled,
           d.chunk_size, d.chunk_overlap, d.embedding_model, d.last_indexed_at,
           d.tags, d.source_path, d.updated_at, d.product_key,
           u.name AS updated_by_name,
           sf.filename,
           (SELECT count(*)::int FROM kb_chunks c WHERE c.document_id = d.id) AS chunk_count
    FROM kb_documents d
    LEFT JOIN users u ON u.id = d.updated_by_user_id
    LEFT JOIN LATERAL (
      SELECT filename
      FROM kb_source_files
      WHERE document_id = d.id
      ORDER BY created_at DESC
      LIMIT 1
    ) sf ON true
"""


def list_kb_documents(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _KB_DOC_SELECT
                    + " ORDER BY d.updated_at DESC, d.id ASC LIMIT :limit OFFSET :offset"
                ),
                {"limit": page, "offset": skip},
            )
        )
    return [_serialize_kb_document(r) for r in rows]


def get_kb_document(document_id: str) -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_KB_DOC_SELECT + " WHERE d.id = :id"),
                {"id": document_id},
            )
        )
    return _serialize_kb_document(row) if row else None


def list_kb_chunks(
    document_id: str, *, limit: int | None = None, offset: int | None = None
) -> list[dict[str, Any]]:
    """Chunks of one document, newest ingest first within chunk order.

    Bounded because every row carries its full chunk ``text``: a long policy PDF
    is thousands of chunks, and the chunk viewer only ever renders a page of
    them. This was the largest single response the API could produce.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, document_id, heading, tokens, text, hits, chunk_index
                    FROM kb_chunks
                    WHERE document_id = :id
                    ORDER BY chunk_index ASC, created_at ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"id": document_id, "limit": page, "offset": skip},
            )
        )
    return [
        {
            "id": r["id"],
            "docId": r["document_id"],
            "index": int(r["chunk_index"]),
            "heading": r.get("heading") or "",
            "tokens": int(r.get("tokens") or 0),
            "text": r.get("text") or "",
            "hits": int(r.get("hits") or 0),
        }
        for r in rows
    ]


def get_kb_stats() -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    with engine.connect() as conn:
        doc_row = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      count(*)::int AS docs,
                      count(*) FILTER (
                        WHERE enabled AND status = 'indexed'
                      )::int AS active_docs,
                      max(last_indexed_at) AS last_indexed
                    FROM kb_documents
                    """
                )
            )
        ) or {"docs": 0, "active_docs": 0, "last_indexed": None}
        faq_row = _one(
            conn.execute(
                text("SELECT count(*)::int AS n FROM faq_pairs WHERE enabled = true")
            )
        ) or {"n": 0}
        chunk_row = _one(
            conn.execute(
                text(
                    """
                    SELECT count(*)::int AS n
                    FROM kb_chunks c
                    JOIN kb_documents d ON d.id = c.document_id
                    WHERE d.enabled = true AND d.status = 'indexed'
                    """
                )
            )
        ) or {"n": 0}
        gap_row = _one(
            conn.execute(
                text(
                    """
                    SELECT count(*)::int AS n
                    FROM unanswered_questions uq
                    WHERE uq.tenant_id = :tenant_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM analytics_kb_gap_links g
                        WHERE g.unanswered_question_id = uq.id
                          AND (g.faq_pair_id IS NOT NULL OR g.kb_document_id IS NOT NULL)
                      )
                    """
                ),
                {"tenant_id": _tenant()},
            )
        ) or {"n": 0}
        score_row = _one(
            conn.execute(
                text(
                    """
                    SELECT avg(score) AS avg_score
                    FROM (
                      SELECT (elem->>'score')::float AS score
                      FROM retrieval_logs rl
                      CROSS JOIN LATERAL jsonb_array_elements(
                        COALESCE(rl.top_chunks, '[]'::jsonb)
                      ) WITH ORDINALITY AS t(elem, ord)
                      WHERE ord = 1
                        AND (elem->>'score') IS NOT NULL
                      ORDER BY rl.created_at DESC
                      LIMIT 100
                    ) s
                    """
                )
            )
        ) or {"avg_score": None}

    last = doc_row.get("last_indexed") or ""
    avg = score_row.get("avg_score")
    try:
        avg_score = float(avg) if avg is not None else 0.0
    except (TypeError, ValueError):
        avg_score = 0.0
    return {
        "docs": int(doc_row.get("docs") or 0),
        "activeDocs": int(doc_row.get("active_docs") or 0),
        "faqs": int(faq_row.get("n") or 0),
        "chunks": int(chunk_row.get("n") or 0),
        "gaps": int(gap_row.get("n") or 0),
        "lastIndexed": last if isinstance(last, str) else (last.isoformat() if last else ""),
        "avgScore": round(avg_score, 4),
    }


def get_kb_index_job(job_id: str) -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, document_id, status, chunk_size, chunk_overlap,
                           embedding_model, started_at, completed_at, error,
                           created_at, updated_at
                    FROM kb_index_jobs
                    WHERE id = :id
                    """
                ),
                {"id": job_id},
            )
        )
    if not row:
        return None
    return {
        "id": row["id"],
        "documentId": row["document_id"],
        "status": row["status"],
        "chunkSize": row.get("chunk_size"),
        "chunkOverlap": row.get("chunk_overlap"),
        "embeddingModel": row.get("embedding_model"),
        "startedAt": row.get("started_at"),
        "completedAt": row.get("completed_at"),
        "error": row.get("error"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def patch_kb_document(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Enable/disable (chunk eviction), title/tags/chunk params. Returns document (+ optional jobId)."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    import kb_ingest

    with engine.begin() as conn:
        existing = _one(
            conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": document_id})
        )
        if not existing:
            raise KeyError(f"kb document not found: {document_id}")

        job_id: str | None = None
        if "enabled" in payload and payload["enabled"] is not None:
            job_id = kb_ingest.set_document_enabled(conn, document_id, bool(payload["enabled"]))

        sets: list[str] = []
        params: dict[str, Any] = {"id": document_id}
        if payload.get("title") is not None:
            sets.append("title = :title")
            params["title"] = str(payload["title"]).strip() or document_id
        if payload.get("tags") is not None:
            import json

            sets.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = json.dumps([str(t) for t in payload["tags"]])
        if payload.get("chunkSize") is not None:
            sets.append("chunk_size = :chunk_size")
            params["chunk_size"] = int(payload["chunkSize"])
        if payload.get("overlap") is not None:
            sets.append("chunk_overlap = :overlap")
            params["overlap"] = int(payload["overlap"])
        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(f"UPDATE kb_documents SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    doc = get_kb_document(document_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def reindex_kb_document(document_id: str) -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    import kb_ingest

    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text("SELECT id, chunk_size, chunk_overlap FROM kb_documents WHERE id = :id"),
                {"id": document_id},
            )
        )
        if not row:
            raise KeyError(f"kb document not found: {document_id}")
        # Drop stale queued/failed jobs for this doc to avoid duplicate work.
        conn.execute(
            text(
                """
                DELETE FROM kb_index_jobs
                WHERE document_id = :id AND status IN ('queued', 'failed')
                """
            ),
            {"id": document_id},
        )
        job_id = kb_ingest.enqueue_index_job(
            conn,
            document_id=document_id,
            chunk_size=row.get("chunk_size"),
            chunk_overlap=row.get("chunk_overlap"),
        )
    return {"jobId": job_id, "documentId": document_id, "status": "queued"}


def reindex_all_kb_documents() -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    import kb_ingest

    job_ids: list[str] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, chunk_size, chunk_overlap
                    FROM kb_documents
                    WHERE enabled = true
                    ORDER BY id
                    """
                )
            )
        )
        for row in rows:
            conn.execute(
                text(
                    """
                    DELETE FROM kb_index_jobs
                    WHERE document_id = :id AND status IN ('queued', 'failed')
                    """
                ),
                {"id": row["id"]},
            )
            job_ids.append(
                kb_ingest.enqueue_index_job(
                    conn,
                    document_id=row["id"],
                    chunk_size=row.get("chunk_size"),
                    chunk_overlap=row.get("chunk_overlap"),
                )
            )
    return {"jobIds": job_ids, "count": len(job_ids)}


def _kb_delete_minio_refs(storage_refs: list[str]) -> int:
    """Best-effort MinIO cleanup; never raises."""
    if not storage_refs:
        return 0
    try:
        import storage as object_store
    except Exception:
        return 0
    removed = 0
    for ref in storage_refs:
        try:
            if object_store.delete_object(ref):
                removed += 1
        except Exception:
            pass
    return removed


def delete_kb_document(document_id: str) -> dict[str, Any]:
    """Hard-delete a KB document (chunks/jobs/files cascade). Best-effort MinIO cleanup."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _one = _mod._one
    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, product_key
                    FROM kb_documents
                    WHERE id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        if not row:
            raise KeyError(f"kb document not found: {document_id}")

        file_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT storage_ref FROM kb_source_files WHERE document_id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        storage_refs = [r["storage_ref"] for r in file_rows if r.get("storage_ref")]

        product_key = row.get("product_key")
        faq_deleted = 0
        if product_key:
            result = conn.execute(
                text("DELETE FROM faq_pairs WHERE id LIKE :prefix"),
                {"prefix": f"faq-{product_key}-%"},
            )
            faq_deleted = int(result.rowcount or 0)

        conn.execute(text("DELETE FROM kb_documents WHERE id = :id"), {"id": document_id})

    minio_removed = _kb_delete_minio_refs(storage_refs)
    return {
        "deleted": True,
        "documentId": document_id,
        "faqsDeleted": faq_deleted,
        "minioObjectsRemoved": minio_removed,
    }


def purge_kb_documents(*, scope: str, confirm: bool) -> dict[str, Any]:
    """Hard-delete documents by scope. Requires confirm=True."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    if not confirm:
        raise ValueError("confirm_required")
    if scope not in ("all", "uploads", "corpus"):
        raise ValueError("invalid_purge_scope")

    with engine.begin() as conn:
        if scope == "uploads":
            where = "product_key IS NULL"
        elif scope == "corpus":
            where = "product_key IS NOT NULL"
        else:
            where = "true"

        docs = _rows(
            conn.execute(text(f"SELECT id, product_key FROM kb_documents WHERE {where}"))
        )
        doc_ids = [d["id"] for d in docs]
        product_keys = sorted({d["product_key"] for d in docs if d.get("product_key")})

        storage_refs: list[str] = []
        if doc_ids:
            # Fetch MinIO refs before cascade delete.
            file_rows = _rows(
                conn.execute(
                    text(
                        """
                        SELECT storage_ref FROM kb_source_files
                        WHERE document_id = ANY(:ids)
                        """
                    ),
                    {"ids": doc_ids},
                )
            )
            storage_refs = [r["storage_ref"] for r in file_rows if r.get("storage_ref")]

        faqs_deleted = 0
        if scope == "all":
            result = conn.execute(text("DELETE FROM faq_pairs"))
            faqs_deleted = int(result.rowcount or 0)
        elif product_keys:
            for pk in product_keys:
                result = conn.execute(
                    text("DELETE FROM faq_pairs WHERE id LIKE :prefix"),
                    {"prefix": f"faq-{pk}-%"},
                )
                faqs_deleted += int(result.rowcount or 0)

        docs_deleted = 0
        if doc_ids:
            result = conn.execute(
                text("DELETE FROM kb_documents WHERE id = ANY(:ids)"),
                {"ids": doc_ids},
            )
            docs_deleted = int(result.rowcount or 0)

    minio_removed = _kb_delete_minio_refs(storage_refs)
    return {
        "scope": scope,
        "documentsDeleted": docs_deleted,
        "faqsDeleted": faqs_deleted,
        "minioObjectsRemoved": minio_removed,
        "documentIds": doc_ids,
    }


def ingest_kb_from_source_db(*, product: str | None = None) -> dict[str, Any]:
    """HTTP wrapper around scripts/ingest_source_db.run_ingest."""
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from ingest_source_db import run_ingest  # type: ignore

    return run_ingest(product_key=product)


def create_kb_document_from_upload(
    *,
    filename: str,
    data: bytes,
    content_type: str,
    title: str | None,
    doc_type: str,
    chunk_size: int,
    overlap: int,
    index_now: bool,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Multipart upload → MinIO + kb_source_files (+ optional index job)."""
    import kb_ingest
    import storage as object_store

    if doc_type not in _KB_ALLOWED_TYPES:
        raise ValueError(f"invalid document type: {doc_type}")
    if not data:
        raise ValueError("empty upload")
    safe_name = Path(filename).name or "upload.txt"
    doc_id = f"kb-upload-{uuid.uuid4().hex[:12]}"
    display_title = (title or "").strip() or Path(safe_name).stem or doc_id
    tag_list = tags or []
    mime = content_type or "application/octet-stream"

    # Fail early on binary we cannot index when indexing is requested.
    if index_now:
        kb_ingest._decode_source_bytes(data, filename=safe_name, mime_type=mime)

    key = object_store.object_key(doc_id, safe_name)
    storage_ref = object_store.put_bytes(key, data, mime)
    file_id = f"file-{doc_id}"
    content_hash = kb_ingest.content_sha256(data)
    job_id: str | None = None

    # The object is already in MinIO. If the rows that give it a name never
    # commit, nothing will ever reference or reclaim it — compensate here so a
    # failed upload does not leave a permanently unreachable blob behind.
    try:
        job_id = _kb_upload_rows(
            doc_id=doc_id,
            file_id=file_id,
            storage_ref=storage_ref,
            safe_name=safe_name,
            mime=mime,
            data=data,
            content_hash=content_hash,
            doc_type=doc_type,
            display_title=display_title,
            tag_list=tag_list,
            chunk_size=chunk_size,
            overlap=overlap,
            index_now=index_now,
        )
    except Exception:
        _discard_orphan_object(storage_ref)
        raise

    doc = get_kb_document(doc_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def _discard_orphan_object(storage_ref: str) -> None:
    """Best-effort delete of an object whose owning rows never committed."""
    import storage as object_store

    try:
        object_store.delete_object(storage_ref)
    except Exception:
        logger.warning("orphaned kb upload not reclaimed: %s", storage_ref, exc_info=True)


def _kb_upload_rows(
    *,
    doc_id: str,
    file_id: str,
    storage_ref: str,
    safe_name: str,
    mime: str,
    data: bytes,
    content_hash: str,
    doc_type: str,
    display_title: str,
    tag_list: list[str],
    chunk_size: int,
    overlap: int,
    index_now: bool,
) -> str | None:
    _mod = _db()
    engine = _mod.engine
    _tenant = _mod._tenant
    _actor_user_id = _mod._actor_user_id
    import json

    import kb_ingest

    job_id: str | None = None
    with engine.begin() as conn:
        status = "indexing" if index_now else "draft"
        enabled = bool(index_now)
        conn.execute(
            text(
                """
                INSERT INTO kb_documents (
                  id, tenant_id, updated_by_user_id, type, version, status, enabled,
                  chunk_size, chunk_overlap, title, tags, embedding_model,
                  product_key, source_path, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :actor, :type, 'v1.0', :status, :enabled,
                  :chunk_size, :overlap, :title, CAST(:tags AS jsonb), NULL,
                  NULL, NULL, now(), now()
                )
                """
            ),
            {
                "id": doc_id,
                "tenant_id": _tenant(),
                "actor": _actor_user_id(),
                "type": doc_type,
                "status": status,
                "enabled": enabled,
                "chunk_size": chunk_size,
                "overlap": overlap,
                "title": display_title,
                "tags": json.dumps(tag_list),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO kb_source_files (
                  id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                ) VALUES (
                  :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                )
                """
            ),
            {
                "id": file_id,
                "document_id": doc_id,
                "storage_ref": storage_ref,
                "filename": safe_name,
                "mime_type": mime,
                "size_bytes": len(data),
                "hash": content_hash,
            },
        )
        if index_now:
            job_id = kb_ingest.enqueue_index_job(
                conn,
                document_id=doc_id,
                chunk_size=chunk_size,
                chunk_overlap=overlap,
            )
    return job_id


def create_kb_document_version(
    document_id: str,
    *,
    filename: str,
    data: bytes,
    content_type: str,
) -> dict[str, Any]:
    """New version upload → MinIO + new kb_source_files row + reindex job."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _actor_user_id = _mod._actor_user_id
    import kb_ingest
    import storage as object_store

    if not data:
        raise ValueError("empty upload")
    safe_name = Path(filename).name or "upload.txt"
    mime = content_type or "application/octet-stream"
    kb_ingest._decode_source_bytes(data, filename=safe_name, mime_type=mime)

    storage_ref: str | None = None
    try:
        with engine.begin() as conn:
            row = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, version, chunk_size, chunk_overlap
                        FROM kb_documents WHERE id = :id
                        FOR UPDATE
                        """
                    ),
                    {"id": document_id},
                )
            )
            if not row:
                raise KeyError(f"kb document not found: {document_id}")

            new_version = _bump_kb_version(row.get("version"))
            # Prefer stable object names per version to retain prior objects.
            object_name = f"{Path(safe_name).stem}-{new_version}{Path(safe_name).suffix or '.txt'}"
            key = object_store.object_key(document_id, object_name)
            storage_ref = object_store.put_bytes(key, data, mime)
            file_id = f"file-{document_id}-{uuid.uuid4().hex[:8]}"
            conn.execute(
                text(
                    """
                    INSERT INTO kb_source_files (
                      id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                    ) VALUES (
                      :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                    )
                    """
                ),
                {
                    "id": file_id,
                    "document_id": document_id,
                    "storage_ref": storage_ref,
                    "filename": safe_name,
                    "mime_type": mime,
                    "size_bytes": len(data),
                    "hash": kb_ingest.content_sha256(data),
                },
            )
            conn.execute(
                text(
                    """
                    UPDATE kb_documents
                    SET version = :version, status = 'indexing', updated_at = now(),
                        updated_by_user_id = :actor
                    WHERE id = :id
                    """
                ),
                {"id": document_id, "version": new_version, "actor": _actor_user_id()},
            )
            conn.execute(
                text(
                    """
                    DELETE FROM kb_index_jobs
                    WHERE document_id = :id AND status IN ('queued', 'failed')
                    """
                ),
                {"id": document_id},
            )
            job_id = kb_ingest.enqueue_index_job(
                conn,
                document_id=document_id,
                chunk_size=row.get("chunk_size"),
                chunk_overlap=row.get("chunk_overlap"),
            )

    except Exception:
        # The version object is written inside the transaction; a later
        # failure rolls the rows back but not the blob.
        if storage_ref:
            _discard_orphan_object(storage_ref)
        raise

    doc = get_kb_document(document_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def backfill_kb_sources_to_minio(*, limit: int | None = None) -> dict[str, Any]:
    """Optional: copy disk source_path originals into MinIO + kb_source_files."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    import kb_ingest
    import storage as object_store

    copied = 0
    skipped = 0
    errors: list[str] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT d.id, d.source_path
                    FROM kb_documents d
                    WHERE d.source_path IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM kb_source_files f WHERE f.document_id = d.id
                      )
                    ORDER BY d.id
                    """
                )
            )
        )
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            path = Path(row["source_path"])
            if not path.is_file():
                skipped += 1
                errors.append(f"{row['id']}: missing {path}")
                continue
            try:
                data = path.read_bytes()
                mime = "text/markdown" if path.suffix.lower() == ".md" else "text/plain"
                key = object_store.object_key(row["id"], path.name)
                storage_ref = object_store.put_bytes(key, data, mime)
                # Savepoint per row: one bad insert must not abort the whole backfill txn.
                with conn.begin_nested():
                    conn.execute(
                        text(
                            """
                            INSERT INTO kb_source_files (
                              id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                            ) VALUES (
                              :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                            )
                            """
                        ),
                        {
                            "id": f"file-{row['id']}",
                            "document_id": row["id"],
                            "storage_ref": storage_ref,
                            "filename": path.name,
                            "mime_type": mime,
                            "size_bytes": len(data),
                            "hash": kb_ingest.content_sha256(data),
                        },
                    )
                copied += 1
            except Exception as exc:
                errors.append(f"{row['id']}: {exc}")
    return {"copied": copied, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Knowledge Base — Phase KB-3 FAQs + Analytics Gaps
# ---------------------------------------------------------------------------


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _embed_faq_pair(question: str, answer: str) -> str | None:
    """Best-effort FAQ embedding for hybrid retrieve. Returns vector literal or None."""
    try:
        import azure_openai

        blob = f"Q: {question.strip()}\nA: {answer.strip()}"
        vec = azure_openai.embed_texts([blob])[0]
        return _vector_literal(vec)
    except Exception:
        return None


def _serialize_kb_faq(row: dict[str, Any]) -> dict[str, Any]:
    updated = row.get("updated_at") or ""
    return {
        "id": row["id"],
        "question": row.get("question") or "",
        "answer": row.get("answer") or "",
        "intent": row.get("intent") or "other",
        "enabled": bool(row.get("enabled")),
        "updatedAt": updated if isinstance(updated, str) else (updated.isoformat() if updated else ""),
        "linkedDocId": row.get("linked_document_id"),
    }


def list_kb_faqs(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled,
                           linked_document_id, updated_at
                    FROM faq_pairs
                    ORDER BY updated_at DESC, id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
            )
        )
    return [_serialize_kb_faq(r) for r in rows]


def get_kb_faq(faq_id: str) -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled,
                           linked_document_id, updated_at
                    FROM faq_pairs
                    WHERE id = :id
                    """
                ),
                {"id": faq_id},
            )
        )
    return _serialize_kb_faq(row) if row else None


def create_kb_faq(payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    question = (payload.get("question") or "").strip()
    answer = (payload.get("answer") or "").strip()
    intent = (payload.get("intent") or "other").strip() or "other"
    if not question or not answer:
        raise ValueError("question and answer are required")

    linked = payload.get("linkedDocId")
    if linked:
        with engine.connect() as conn:
            doc = _one(
                conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": linked})
            )
            if not doc:
                raise ValueError(f"linked document not found: {linked}")

    faq_id = f"faq-{uuid.uuid4().hex[:12]}"
    embedding = _embed_faq_pair(question, answer)
    if embedding is None:
        logger.warning("faq_create_without_embedding faq_id=%s", faq_id)
    gap_id = payload.get("gapId")

    with engine.begin() as conn:
        if embedding is None:
            conn.execute(
                text(
                    """
                    INSERT INTO faq_pairs (
                      id, linked_document_id, intent, question, answer, enabled,
                      embedding, created_at, updated_at
                    ) VALUES (
                      :id, :linked, :intent, :question, :answer, :enabled,
                      NULL, now(), now()
                    )
                    """
                ),
                {
                    "id": faq_id,
                    "linked": linked,
                    "intent": intent,
                    "question": question,
                    "answer": answer,
                    "enabled": bool(payload.get("enabled", True)),
                },
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO faq_pairs (
                      id, linked_document_id, intent, question, answer, enabled,
                      embedding, created_at, updated_at
                    ) VALUES (
                      :id, :linked, :intent, :question, :answer, :enabled,
                      CAST(:embedding AS vector), now(), now()
                    )
                    """
                ),
                {
                    "id": faq_id,
                    "linked": linked,
                    "intent": intent,
                    "question": question,
                    "answer": answer,
                    "enabled": bool(payload.get("enabled", True)),
                    "embedding": embedding,
                },
            )
        if gap_id:
            _link_kb_gap_conn(conn, gap_id, faq_pair_id=faq_id)

    row = get_kb_faq(faq_id)
    assert row is not None
    return row


def patch_kb_faq(faq_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    # Validate under a short transaction, then embed *outside* any checked-out
    # connection so Azure latency cannot pin a pool slot.
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled, linked_document_id
                    FROM faq_pairs WHERE id = :id
                    """
                ),
                {"id": faq_id},
            )
        )
        if not existing:
            raise KeyError(f"faq not found: {faq_id}")

        question = existing["question"]
        answer = existing["answer"]
        sets: list[str] = []
        params: dict[str, Any] = {"id": faq_id}
        reembed = False

        if "question" in payload and payload["question"] is not None:
            question = str(payload["question"]).strip()
            if not question:
                raise ValueError("question cannot be empty")
            sets.append("question = :question")
            params["question"] = question
            reembed = True
        if "answer" in payload and payload["answer"] is not None:
            answer = str(payload["answer"]).strip()
            if not answer:
                raise ValueError("answer cannot be empty")
            sets.append("answer = :answer")
            params["answer"] = answer
            reembed = True
        if "intent" in payload and payload["intent"] is not None:
            sets.append("intent = :intent")
            params["intent"] = str(payload["intent"]).strip() or "other"
        if "enabled" in payload and payload["enabled"] is not None:
            sets.append("enabled = :enabled")
            params["enabled"] = bool(payload["enabled"])
        if "linkedDocId" in payload:
            linked = payload["linkedDocId"]
            if linked:
                doc = _one(
                    conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": linked})
                )
                if not doc:
                    raise ValueError(f"linked document not found: {linked}")
            sets.append("linked_document_id = :linked")
            params["linked"] = linked

        if sets and not reembed:
            sets.append("updated_at = now()")
            conn.execute(
                text(f"UPDATE faq_pairs SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    if reembed:
        emb = _embed_faq_pair(question, answer)
        if emb is None:
            logger.warning("faq_reembed_skipped faq_id=%s reason=embed_none", faq_id)
        else:
            sets.append("embedding = CAST(:embedding AS vector)")
            params["embedding"] = emb
        sets.append("updated_at = now()")
        with engine.begin() as conn:
            res = conn.execute(
                text(f"UPDATE faq_pairs SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
            # The non-reembed branch raises on a missing row; this one silently
            # reported success for a deleted FAQ.
            if res.rowcount == 0:
                raise KeyError(f"faq not found: {faq_id}")

    row = get_kb_faq(faq_id)
    assert row is not None
    return row


def delete_kb_faq(faq_id: str) -> None:
    """Delete an FAQ pair. analytics_kb_gap_links.faq_pair_id is ON DELETE SET NULL."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.begin() as conn:
        existing = _one(
            conn.execute(text("SELECT id FROM faq_pairs WHERE id = :id"), {"id": faq_id})
        )
        if not existing:
            raise KeyError(f"faq not found: {faq_id}")
        conn.execute(text("DELETE FROM faq_pairs WHERE id = :id"), {"id": faq_id})


def _normalize_suggested_fix(value: str | None) -> str:
    v = (value or "kb").strip().lower()
    if v in ("kb", "prompt", "both"):
        return v
    return "kb"


# A question shorter than this is not a content gap — it is "ok", "haan", a
# stray STT fragment, or a barge-in. Recording those buries the real gaps.
KB_GAP_MIN_CHARS = 8
# Long enough for a real question, short enough that the KB-gap table stays
# readable and one runaway turn cannot store a transcript.
KB_GAP_MAX_CHARS = 300


def record_kb_gap(
    *,
    question: str,
    intent: str | None = None,
    channel: str | None = None,
    interaction_id: str | None = None,
    conn: Any | None = None,
) -> str | None:
    """Record that the bot could not answer ``question``. Upsert, not insert.

    Returns the gap id, or ``None`` when the question was too short to be worth
    recording. ``channel`` and ``interaction_id`` are accepted for call-site
    symmetry and logging; the table deliberately does not store them — the
    screen aggregates across channels and a per-sighting FK would turn a
    counter into an event log.

    The question is redacted before it is stored. Callers hand us whatever the
    customer said, which on a collections line routinely contains a card or
    mobile number read aloud.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    import pii_redact

    q = " ".join((pii_redact.redact_text(question) or "").split()).strip()
    if len(q) < KB_GAP_MIN_CHARS:
        return None
    q = q[:KB_GAP_MAX_CHARS]

    # "unknown" is what the KB handler's gate produces when no intent was
    # resolved (voice passes apply_intent_gate=False, so it always does). Stored
    # verbatim it becomes a literal "unknown" bucket on the gap screen, sitting
    # next to the "other" bucket that NULL already renders as. Collapse it.
    top_intent = (intent or "").strip().lower()
    if top_intent in {"", "unknown", "other", "none"}:
        top_intent = None

    params = {
        "id": _id("GAP"),
        "tenant_id": _tenant(),
        "question": q,
        "top_intent": top_intent,
    }
    sql = text(
        """
        INSERT INTO unanswered_questions
          (id, tenant_id, question, hit_count, last_seen_at,
           suggested_fix_type, top_intent, created_at, updated_at)
        VALUES
          (:id, :tenant_id, :question, 1, now(), 'kb', :top_intent, now(), now())
        ON CONFLICT (tenant_id, lower(btrim(question))) DO UPDATE SET
          hit_count = unanswered_questions.hit_count + 1,
          last_seen_at = now(),
          -- COALESCE keeps the FIRST intent seen rather than the latest: the
          -- screen groups by it, and a single off-topic sighting should not
          -- relabel a gap that has been asked fifty times.
          top_intent = COALESCE(unanswered_questions.top_intent, EXCLUDED.top_intent),
          -- suggested_fix_type is deliberately NOT touched. It starts at 'kb'
          -- and an operator may switch it to 'prompt'/'both'; overwriting on
          -- every sighting would silently revert their triage decision.
          updated_at = now()
        RETURNING id
        """
    )

    if conn is not None:
        row = _one(conn.execute(sql, params))
        return row["id"] if row else None
    with engine.begin() as own:
        row = _one(own.execute(sql, params))
    return row["id"] if row else None


def purge_stale_kb_gaps(*, ttl_days: int = 90, conn: Any | None = None) -> int:
    """Drop one-off gaps nobody acted on. Returns rows deleted.

    Two guards, both load-bearing. ``hit_count = 1`` keeps anything asked more
    than once, which is the definition of a recurring gap. ``NOT EXISTS`` keeps
    anything an operator linked to a doc, FAQ or prompt version — those links
    cascade from this table, so deleting a linked gap would destroy the record
    that someone already fixed it.
    """
    _mod = _db()
    engine = _mod.engine
    _tenant = _mod._tenant
    sql = text(
        """
        DELETE FROM unanswered_questions uq
         WHERE uq.tenant_id = :tenant_id
           AND uq.hit_count <= 1
           AND uq.last_seen_at IS NOT NULL
           AND uq.last_seen_at < now() - CAST(:window AS interval)
           AND NOT EXISTS (
             SELECT 1 FROM analytics_kb_gap_links g
              WHERE g.unanswered_question_id = uq.id
           )
        """
    )
    params = {"tenant_id": _tenant(), "window": f"{max(1, int(ttl_days))} days"}
    if conn is not None:
        return conn.execute(sql, params).rowcount or 0
    with engine.begin() as own:
        return own.execute(sql, params).rowcount or 0


# The screen pages and sorts by hit_count; before runtime capture this table was
# hand-seeded at ~10 rows and unbounded was fine. It now grows with traffic.
KB_GAP_LIST_LIMIT = 200


def list_kb_gaps() -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      uq.id,
                      uq.question,
                      uq.hit_count,
                      uq.last_seen_at,
                      coalesce(uq.top_intent, 'other') AS top_intent,
                      uq.suggested_fix_type,
                      g.kb_document_id,
                      g.faq_pair_id,
                      g.prompt_version_id
                    FROM unanswered_questions uq
                    LEFT JOIN LATERAL (
                      SELECT kb_document_id, faq_pair_id, prompt_version_id
                      FROM analytics_kb_gap_links
                      WHERE unanswered_question_id = uq.id
                      ORDER BY created_at DESC
                      LIMIT 1
                    ) g ON true
                    WHERE uq.tenant_id = :tenant_id
                    ORDER BY uq.hit_count DESC NULLS LAST, uq.id
                    LIMIT :lim
                    """
                ),
                {"tenant_id": _tenant(), "lim": KB_GAP_LIST_LIMIT},
            )
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        has_doc = bool(r.get("kb_document_id"))
        has_faq = bool(r.get("faq_pair_id"))
        has_prompt = bool(r.get("prompt_version_id"))
        last = r.get("last_seen_at") or ""
        out.append(
            {
                "id": r["id"],
                "text": r.get("question") or "",
                "hits": int(r.get("hit_count") or 0),
                "lastSeen": last if isinstance(last, str) else (last.isoformat() if last else ""),
                "topIntent": r.get("top_intent") or "other",
                "hasKbDoc": has_doc,
                "hasFaq": has_faq,
                "resolved": has_doc or has_faq or has_prompt,
                "suggestedFix": _normalize_suggested_fix(r.get("suggested_fix_type")),
                "linkedDocumentId": r.get("kb_document_id"),
                "linkedFaqId": r.get("faq_pair_id"),
                "linkedPromptVersionId": r.get("prompt_version_id"),
            }
        )
    return out


def _link_kb_gap_conn(
    conn: Any,
    gap_id: str,
    *,
    faq_pair_id: str | None = None,
    kb_document_id: str | None = None,
    prompt_version_id: str | None = None,
) -> None:
    _mod = _db()
    _one = _mod._one
    _tenant = _mod._tenant
    targets = [
        ("faqPairId", faq_pair_id),
        ("kbDocumentId", kb_document_id),
        ("promptVersionId", prompt_version_id),
    ]
    provided = [(k, v) for k, v in targets if v]
    if not provided:
        raise ValueError("faqPairId_kbDocumentId_or_promptVersionId_required")
    if len(provided) > 1:
        raise ValueError("gap_link_exactly_one_target")

    gap = _one(
        conn.execute(
            text(
                """
                SELECT id FROM unanswered_questions
                WHERE id = :id AND tenant_id = :tenant_id
                """
            ),
            {"id": gap_id, "tenant_id": _tenant()},
        )
    )
    if not gap:
        raise KeyError(f"gap not found: {gap_id}")

    if faq_pair_id:
        faq = _one(
            conn.execute(text("SELECT id FROM faq_pairs WHERE id = :id"), {"id": faq_pair_id})
        )
        if not faq:
            raise KeyError(f"faq not found: {faq_pair_id}")
    if kb_document_id:
        doc = _one(
            conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": kb_document_id})
        )
        if not doc:
            raise KeyError(f"document not found: {kb_document_id}")
    if prompt_version_id:
        pv = _one(
            conn.execute(
                text("SELECT id FROM prompt_versions WHERE id = :id"),
                {"id": prompt_version_id},
            )
        )
        if not pv:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

    existing = _one(
        conn.execute(
            text(
                """
                SELECT id, faq_pair_id, kb_document_id, prompt_version_id
                FROM analytics_kb_gap_links
                WHERE unanswered_question_id = :id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"id": gap_id},
        )
    )
    if existing:
        # Replace link targets — exactly one of the three columns is set.
        conn.execute(
            text(
                """
                UPDATE analytics_kb_gap_links
                SET faq_pair_id = :faq_pair_id,
                    kb_document_id = :kb_document_id,
                    prompt_version_id = :prompt_version_id
                WHERE id = :id
                """
            ),
            {
                "id": existing["id"],
                "faq_pair_id": faq_pair_id,
                "kb_document_id": kb_document_id,
                "prompt_version_id": prompt_version_id,
            },
        )
        return

    conn.execute(
        text(
            """
            INSERT INTO analytics_kb_gap_links (
              id, unanswered_question_id, kb_document_id, faq_pair_id,
              prompt_version_id, routing_rule_id, created_at
            ) VALUES (
              :id, :gap_id, :kb_document_id, :faq_pair_id,
              :prompt_version_id, NULL, now()
            )
            """
        ),
        {
            "id": f"gap-link-{uuid.uuid4().hex[:10]}",
            "gap_id": gap_id,
            "kb_document_id": kb_document_id,
            "faq_pair_id": faq_pair_id,
            "prompt_version_id": prompt_version_id,
        },
    )


def link_kb_gap(gap_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    with engine.begin() as conn:
        _link_kb_gap_conn(
            conn,
            gap_id,
            faq_pair_id=payload.get("faqPairId"),
            kb_document_id=payload.get("kbDocumentId"),
            prompt_version_id=payload.get("promptVersionId"),
        )
    gaps = {g["id"]: g for g in list_kb_gaps()}
    if gap_id not in gaps:
        raise KeyError(f"gap not found: {gap_id}")
    return gaps[gap_id]


