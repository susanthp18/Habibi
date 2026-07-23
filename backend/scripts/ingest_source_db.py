"""Bootstrap HDFC insurance corpus from source_db/ (disk) into kb_* + faq_pairs.

Usage (from backend/):
  .venv/Scripts/python scripts/ingest_source_db.py
  .venv/Scripts/python scripts/ingest_source_db.py --validate-only
  .venv/Scripts/python scripts/ingest_source_db.py --product car
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Allow `python scripts/ingest_source_db.py` from backend/
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import text

import azure_openai
import db
from env_loader import load_env
from kb_chunking import faq_id, faq_intent, parse_faq_qa
from kb_corpus_manifest import CORPUS_MANIFEST, CorpusProduct, validate_manifest
from kb_ingest import drain_queue, enqueue_index_job, upsert_document

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("ingest_source_db")


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _upsert_faqs(
    conn,
    *,
    product: CorpusProduct,
    faq_path: Path,
    linked_document_id: str,
) -> int:
    raw = faq_path.read_text(encoding="utf-8")
    drafts = parse_faq_qa(raw)
    if not drafts:
        raise ValueError(f"No Q:/A: pairs parsed from {faq_path}")

    # Embed question+answer for hybrid retrieval (dim-asserted in azure client).
    texts = [f"Q: {d.question}\nA: {d.answer}" for d in drafts]
    vectors = azure_openai.embed_texts(texts)

    # Replace product FAQ set atomically for idempotent re-runs.
    conn.execute(
        text("DELETE FROM faq_pairs WHERE id LIKE :prefix"),
        {"prefix": f"faq-{product.product_key}-%"},
    )

    for i, (draft, vec) in enumerate(zip(drafts, vectors, strict=True), start=1):
        fid = faq_id(product.product_key, i)
        conn.execute(
            text(
                """
                INSERT INTO faq_pairs (
                  id, linked_document_id, intent, question, answer, enabled,
                  embedding, created_at, updated_at
                ) VALUES (
                  :id, :linked_document_id, :intent, :question, :answer, true,
                  CAST(:embedding AS vector), now(), now()
                )
                """
            ),
            {
                "id": fid,
                "linked_document_id": linked_document_id,
                "intent": faq_intent(product.product_key, draft.question),
                "question": draft.question,
                "answer": draft.answer,
                "embedding": _vector_literal(vec),
            },
        )
    return len(drafts)


def ingest_product(product: CorpusProduct, paths: dict[str, Path]) -> dict[str, Any]:
    policy_id = f"kb-policy-{product.product_key}"
    benefits_id = f"kb-benefits-{product.product_key}"

    with db.engine.begin() as conn:
        upsert_document(
            conn,
            doc_id=policy_id,
            title=f"{product.title} — Policy",
            doc_type="policy",
            product_key=product.product_key,
            source_path=str(paths["policy"]),
            tags=[product.product_key, "policy", "hdfc", "upsell"],
        )
        upsert_document(
            conn,
            doc_id=benefits_id,
            title=f"{product.title} — Benefits",
            doc_type="benefits",
            product_key=product.product_key,
            source_path=str(paths["benefits"]),
            tags=[product.product_key, "benefits", "hdfc", "upsell"],
        )
        # Drop stale queued/failed jobs so re-runs don't pile up; always new job ids.
        conn.execute(
            text(
                """
                DELETE FROM kb_index_jobs
                WHERE document_id IN (:p, :b) AND status IN ('queued', 'failed')
                """
            ),
            {"p": policy_id, "b": benefits_id},
        )
        enqueue_index_job(conn, document_id=policy_id)
        enqueue_index_job(conn, document_id=benefits_id)

    # Process jobs outside the FAQ txn so embed failures don't orphan FAQ deletes mid-flight.
    jobs_drained = drain_queue(db.engine)
    logger.info("product=%s index_jobs_drained=%s", product.product_key, jobs_drained)

    with db.engine.begin() as conn:
        faq_count = _upsert_faqs(
            conn,
            product=product,
            faq_path=paths["faq"],
            linked_document_id=policy_id,
        )
    logger.info("product=%s faqs=%s", product.product_key, faq_count)
    return {
        "productKey": product.product_key,
        "jobsDrained": jobs_drained,
        "faqs": faq_count,
    }


def _corpus_counts() -> dict[str, int]:
    with db.engine.connect() as conn:
        docs = conn.execute(
            text("SELECT count(*) FROM kb_documents WHERE product_key IS NOT NULL")
        ).scalar()
        chunks = conn.execute(
            text(
                """
                SELECT count(*) FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE d.product_key IS NOT NULL AND c.embedding IS NOT NULL
                """
            )
        ).scalar()
        faqs = conn.execute(
            text("SELECT count(*) FROM faq_pairs WHERE id LIKE 'faq-%' AND embedding IS NOT NULL")
        ).scalar()
    return {
        "docs": int(docs or 0),
        "chunks": int(chunks or 0),
        "faqs": int(faqs or 0),
    }


def run_ingest(*, product_key: str | None = None) -> dict[str, Any]:
    """Shared entry for CLI and HTTP. Embeds + indexes selected corpus products."""
    load_env()
    resolved = validate_manifest(CORPUS_MANIFEST)
    azure_openai.get_embedding_dims()
    azure_openai.get_embedding_deployment()

    selected = resolved
    if product_key:
        selected = [(p, paths) for p, paths in resolved if p.product_key == product_key]
        if not selected:
            valid = [p.product_key for p, _ in resolved]
            raise ValueError(f"Unknown product_key {product_key!r}. Valid: {valid}")

    product_results: list[dict[str, Any]] = []
    jobs_drained = 0
    faqs_total = 0
    for product, paths in selected:
        logger.info("ingesting product=%s", product.product_key)
        result = ingest_product(product, paths)
        product_results.append(result)
        jobs_drained += int(result.get("jobsDrained") or 0)
        faqs_total += int(result.get("faqs") or 0)

    counts = _corpus_counts()
    out = {
        "products": [r["productKey"] for r in product_results],
        "jobsDrained": jobs_drained,
        "faqsUpserted": faqs_total,
        "docs": counts["docs"],
        "chunks": counts["chunks"],
        "faqs": counts["faqs"],
    }
    logger.info(
        "done products=%s jobs=%s faqs_upserted=%s docs=%s chunks=%s faqs=%s",
        len(out["products"]),
        out["jobsDrained"],
        out["faqsUpserted"],
        out["docs"],
        out["chunks"],
        out["faqs"],
    )
    return out


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Ingest source_db corpus into KB")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--product", help="Ingest a single product_key")
    parser.add_argument("--smoke-azure", action="store_true", help="Ping Azure embed+chat then exit")
    args = parser.parse_args()

    if args.smoke_azure:
        result = azure_openai.smoke_test()
        print(json.dumps(result, indent=2))
        return

    resolved = validate_manifest(CORPUS_MANIFEST)
    logger.info("manifest_ok products=%s", len(resolved))
    if args.validate_only:
        for product, paths in resolved:
            print(
                f"OK {product.product_key}: {paths['policy'].name}, "
                f"{paths['faq'].name}, {paths['benefits'].name}"
            )
        return

    try:
        out = run_ingest(product_key=args.product)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    logger.info("done docs=%s embedded_chunks=%s embedded_faqs=%s", out["docs"], out["chunks"], out["faqs"])


if __name__ == "__main__":
    main()
