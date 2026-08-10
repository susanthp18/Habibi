"""SKIP LOCKED claim — concurrent claimers never share a job."""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text


def test_two_claimers_never_take_same_job() -> None:
    import db
    import kb_ingest

    with db.engine.connect() as conn:
        doc = conn.execute(text("SELECT id FROM kb_documents LIMIT 1")).fetchone()
    if doc is None:
        pytest.skip("no kb_documents for job FK")

    document_id = doc[0]
    job_id = f"kb-job-claim-ut-{uuid.uuid4().hex[:10]}"
    park_marker = f"[parked-ut-{job_id}]"

    # Park other queued jobs so only ours is claimable.
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE kb_index_jobs
                SET status = 'failed',
                    error = COALESCE(error, '') || :marker,
                    updated_at = now()
                WHERE status = 'queued'
                """
            ),
            {"marker": park_marker},
        )
        conn.execute(
            text(
                """
                INSERT INTO kb_index_jobs (
                  id, document_id, status, chunk_size, chunk_overlap,
                  embedding_model, created_at, updated_at
                ) VALUES (
                  :id, :document_id, 'queued', 800, 120,
                  'text-embedding-3-small', now(), now()
                )
                """
            ),
            {"id": job_id, "document_id": document_id},
        )

    results: list[str | None] = [None, None]
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def claimer(idx: int) -> None:
        try:
            with db.engine.begin() as conn:
                barrier.wait(timeout=5)
                job = kb_ingest.claim_next_job(conn)
                results[idx] = None if job is None else job["id"]
        except BaseException as exc:  # noqa: BLE001 — surface in main thread
            errors.append(exc)

    t0 = threading.Thread(target=claimer, args=(0,))
    t1 = threading.Thread(target=claimer, args=(1,))
    t0.start()
    t1.start()
    try:
        t0.join(timeout=15)
        t1.join(timeout=15)
    finally:
        # Liveness first, before ANY cleanup SQL. A claimer still inside its
        # transaction holds a row lock on job_id, so the DELETE below would
        # block on it — turning a hung-thread failure into a hung test. Also,
        # unparking is only safe once both claimers are gone: a live thread
        # would otherwise race the rows we requeue.
        if t0.is_alive() or t1.is_alive():
            raise AssertionError("claimer thread did not finish; leaving jobs parked")

        # Cleanup always runs — a failed assertion below must not leave the
        # synthetic job row behind for the next test.
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM kb_index_jobs WHERE id = :id"), {"id": job_id})

        with db.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE kb_index_jobs
                    SET status = 'queued',
                        error = NULLIF(replace(COALESCE(error, ''), :marker, ''), ''),
                        updated_at = now()
                    WHERE status = 'failed' AND error LIKE :like
                    """
                ),
                {"marker": park_marker, "like": f"%{park_marker}%"},
            )

    assert not errors, errors
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, f"expected exactly one claimer to win, got {results}"
    assert claimed[0] == job_id
    assert results.count(None) == 1
