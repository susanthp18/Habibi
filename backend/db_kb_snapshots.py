"""KB snapshots: a frozen set of enabled documents and FAQs a sandbox run pins.

Carved out of ``db_inbox.py`` (WP-036 peel); call sites stay ``import db``.
The engine is reached through ``db`` at call time so the test savepoint proxy applies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from db_core import (
    _db,
    _rows,
    _tenant,
    clamp_list_limit,
    clamp_offset,
)

logger = logging.getLogger(__name__)


def _engine():
    """The engine, resolved at call time.

    ``tests/conftest.py`` replaces ``db.engine`` with a savepoint proxy by
    setattr on the module object. Binding the name here at import time would
    take the real engine and silently escape that proxy.
    """
    return _db().engine


def create_kb_snapshot(*, label: str | None = None) -> dict[str, Any]:
    """Freeze currently enabled indexed docs + enabled FAQs for sandbox readiness."""
    import json

    snap_id = f"kb-snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    label_text = (label or "").strip() or f"KB snapshot {datetime.now(timezone.utc).date().isoformat()}"
    with _engine().begin() as conn:
        docs = _rows(
            conn.execute(
                text(
                    """
                    SELECT id FROM kb_documents
                    WHERE enabled = true AND status = 'indexed'
                    ORDER BY id
                    """
                )
            )
        )
        faqs = _rows(
            conn.execute(
                text(
                    """
                    SELECT id FROM faq_pairs
                    WHERE enabled = true
                    ORDER BY id
                    """
                )
            )
        )
        doc_ids = [d["id"] for d in docs]
        faq_ids = [f["id"] for f in faqs]
        conn.execute(
            text(
                """
                INSERT INTO kb_snapshots
                  (id, tenant_id, label, document_ids, faq_ids, created_at)
                VALUES (:id, :tenant_id, :label, CAST(:document_ids AS jsonb),
                        CAST(:faq_ids AS jsonb), now())
                """
            ),
            {
                "id": snap_id,
                "tenant_id": _tenant(),
                "label": label_text,
                "document_ids": json.dumps(doc_ids),
                "faq_ids": json.dumps(faq_ids),
            },
        )
    return {
        "id": snap_id,
        "label": label_text,
        "documentIds": doc_ids,
        "faqIds": faq_ids,
        "documentCount": len(doc_ids),
        "faqCount": len(faq_ids),
    }


def list_kb_snapshots(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, label, document_ids, faq_ids, created_at
                    FROM kb_snapshots
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
            )
        )
    out = []
    for r in rows:
        docs = r.get("document_ids") or []
        faqs = r.get("faq_ids") or []
        if isinstance(docs, str):
            import json

            docs = json.loads(docs)
        if isinstance(faqs, str):
            import json

            faqs = json.loads(faqs)
        created = r.get("created_at")
        if created is not None and hasattr(created, "isoformat"):
            created = created.isoformat()
        out.append(
            {
                "id": r["id"],
                "label": r.get("label") or r["id"],
                "documentIds": docs,
                "faqIds": faqs,
                "documentCount": len(docs),
                "faqCount": len(faqs),
                "createdAt": created,
            }
        )
    return out
