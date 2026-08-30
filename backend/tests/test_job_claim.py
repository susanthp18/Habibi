"""SKIP LOCKED claim — concurrent claimers never share a job.

WHY THIS TEST DEFENDS ITSELF AGAINST A THIRD CLAIMER
====================================================
This suite runs against the *shared* development Postgres (docker
``collections_db``), and the dev machine also runs the production-style stack
natively — including two ``python -m worker`` processes (``backend/worker.py``,
"KB index worker — claim queued kb_index_jobs with SKIP LOCKED"). Each polls
every 2 seconds with the exact query this test is about.

So the table under test has live claimers on it. The test parks every queued
job, inserts one synthetic job, and races two threads for it — and a worker
that polls inside the window between the INSERT committing and the two threads
issuing their SELECTs takes that job first. It is the only queued row and the
claim is oldest-first, so it is precisely what the worker is hunting for. Both
test threads then correctly come back empty, ``results`` is ``[None, None]``,
and the assertions at the bottom fail. Teardown deletes the synthetic row, so
the thief leaves no trace and the failure reads like a SKIP LOCKED bug that
does not exist. Cost of rediscovering this: one very confusing night.

Do NOT "fix" it by stopping the workers — they serve the running product. Two
things are done here instead.

1.  The window is made as small as it can be. Both claimer threads open their
    connection and transaction *before* the synthetic job exists and park on a
    barrier, so what is exposed is one INSERT commit plus a barrier release
    rather than two thread starts plus two connection-pool checkouts.

2.  Whatever window is left is *proved*, not assumed. If neither thread got the
    probe job, the test establishes whether a foreign session took it, from
    three independent pieces of evidence (below), and only then skips — loudly,
    naming worker contention and quoting what it saw. If the row was still
    there, still unlocked, and both claimers still came back empty, no foreign
    session is implicated: that is a real SKIP LOCKED defect and the original
    assertions fail exactly as they should. The contract is never weakened, it
    is only ever declared unexercised.

The three pieces of evidence, in the order they are trusted:

*   The post-race row state, read with a *blocking* ``FOR UPDATE`` so it waits
    out a thief's in-flight transaction instead of racing it. A committed
    foreign claim shows up as ``status='running'`` with ``started_at`` set, or
    as the row being gone.
*   ``visible`` — whether a claimer that came back empty could see the row as
    queued at all. Not visible means someone else's status change had already
    committed.
*   ``lockable`` — whether the row's lock was free. Visible-but-not-lockable,
    with neither of our own threads holding it, means a third session had it
    mid-claim. This is the only signal that catches a foreign claimer whose
    transaction later rolls back, which leaves no other trace anywhere.
"""

from __future__ import annotations

import threading
import uuid
import warnings
from typing import Any

import pytest
from sqlalchemy import text

# The forensic read below waits on a thief's transaction rather than racing it.
# Bounded, so a genuinely wedged session fails the run instead of hanging it —
# and kept under this process' 15s statement_timeout so the lock wait is what
# reports the problem.
_FORENSIC_LOCK_TIMEOUT = "10s"


def _probe_state(conn, job_id: str) -> dict[str, Any]:
    """What a claimer that came back empty could still see of the probe row.

    ``visible``  — the row is queued in this transaction's snapshot.
    ``lockable`` — its row lock is free.

    The FOR UPDATE is taken inside a SAVEPOINT and rolled straight back, which
    releases the lock again. Without that, the first thread to ask would end up
    holding the lock and the second would be told a foreigner had it.

    That is necessary but not sufficient: the savepoint bounds how *long* the
    lock is held, not *when*, and two claimers probing at once still overlap.
    Callers must therefore serialise this — see ``probe_gate`` below. Both
    guards earn their place; dropping either one makes a claimer mistake its
    partner for a live worker and excuse a genuine SKIP LOCKED defect.
    """
    visible = (
        conn.execute(
            text("SELECT count(*) FROM kb_index_jobs WHERE id = :id AND status = 'queued'"),
            {"id": job_id},
        ).scalar()
        == 1
    )
    savepoint = conn.begin_nested()
    try:
        lockable = (
            conn.execute(
                text(
                    """
                    SELECT id FROM kb_index_jobs
                    WHERE id = :id AND status = 'queued'
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"id": job_id},
            ).fetchone()
            is not None
        )
    finally:
        savepoint.rollback()
    return {"visible": visible, "lockable": lockable}


def test_two_claimers_never_take_same_job() -> None:
    import db
    import kb_ingest

    # A throwaway document, not the first real one in the table.
    #
    # The synthetic job needs a document_id for its FK, and the obvious way to
    # get one is `SELECT id FROM kb_documents LIMIT 1`. That hands a live
    # `python -m worker` — which polls this very queue every 2 seconds — a job
    # pointing at a REAL document, with this test's chunk parameters. On a
    # machine whose kb-sources MinIO bucket resolves, a stolen claim does not
    # merely take the job: it reindexes production content at 800/120 and
    # overwrites that document's chunks and embeddings.
    #
    # The theft is already detected and reported below; the point of this row
    # is that when it happens, the thief operates on garbage. `disabled` and
    # `status='draft'` so nothing else sweeps it up either.
    document_id = f"kb-doc-claim-ut-{uuid.uuid4().hex[:10]}"
    job_id = f"kb-job-claim-ut-{uuid.uuid4().hex[:10]}"
    park_marker = f"[parked-ut-{job_id}]"

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO kb_documents (
                  id, tenant_id, type, version, status, enabled,
                  title, created_at, updated_at
                ) VALUES (
                  :id, :tenant, 'faq', 'ut', 'draft', false,
                  :title, now(), now()
                )
                """
            ),
            {
                "id": document_id,
                "tenant": db.current_tenant(),
                "title": f"[test probe] job-claim {document_id}",
            },
        )

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

    results: list[str | None] = [None, None]
    # Set by a claimer that did not get the probe job — the only vantage point
    # from which "it was there and free" can be told apart from "someone had it".
    empty_handed: list[dict[str, Any] | None] = [None, None]
    # Three parties: the main thread joins the barrier so the claimers are
    # already connected and in-transaction when the probe job appears, rather
    # than doing their pool checkout inside the window a live worker can poll.
    barrier = threading.Barrier(3)
    # The claimers race, but their *post-mortem* probes must not: a probe takes
    # the row lock for the length of a savepoint, and an overlapping partner
    # would read that as "a third session has it" and skip a run that should
    # have failed. Verified — without this gate the negative control (both
    # claimers empty against a present, queued, unlocked row) is excused as
    # worker contention instead of failing.
    probe_gate = threading.Lock()
    errors: list[BaseException] = []

    def claimer(idx: int) -> None:
        try:
            with db.engine.begin() as conn:
                barrier.wait(timeout=15)
                job = kb_ingest.claim_next_job(conn)
                results[idx] = None if job is None else job["id"]
                if results[idx] != job_id:
                    with probe_gate:
                        empty_handed[idx] = _probe_state(conn, job_id)
        except BaseException as exc:  # noqa: BLE001 — surface in main thread
            errors.append(exc)

    t0 = threading.Thread(target=claimer, args=(0,))
    t1 = threading.Thread(target=claimer, args=(1,))
    t0.start()
    t1.start()

    pre_race_status: str | None = None
    row_present = False
    observed: dict[str, Any] | None = None
    try:
        with db.engine.begin() as conn:
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

        # The starting line. If a worker already took the job between that
        # commit and here, the skip reason below says so, instead of leaving the
        # next reader to guess whether it was taken before or during the race.
        with db.engine.connect() as conn:
            pre_race_status = conn.execute(
                text("SELECT status FROM kb_index_jobs WHERE id = :id"), {"id": job_id}
            ).scalar()

        barrier.wait(timeout=15)
    except BaseException:
        # Do not leave the claimers parked for the full barrier timeout when the
        # main thread never made it to the starting line.
        barrier.abort()
        raise
    finally:
        # Liveness first, before ANY cleanup SQL. A claimer still inside its
        # transaction holds a row lock on job_id, so the DELETE below would
        # block on it — turning a hung-thread failure into a hung test. Also,
        # unparking is only safe once both claimers are gone: a live thread
        # would otherwise race the rows we requeue.
        t0.join(timeout=15)
        t1.join(timeout=15)
        if t0.is_alive() or t1.is_alive():
            raise AssertionError("claimer thread did not finish; leaving jobs parked")

        # Cleanup always runs — a failed assertion below must not leave the
        # synthetic job row behind for the next test. The forensic read shares
        # the DELETE's transaction: plain FOR UPDATE (no SKIP LOCKED) so it
        # *waits out* a thief still inside its claim transaction and reports the
        # committed truth, and a bounded lock_timeout so a wedged session is a
        # loud failure rather than a hang. Because they share a transaction, a
        # raising read rolls the DELETEs back with it — hence the re-sweep. The
        # unpark is nested one level deeper so it runs regardless.
        swept = False
        try:
            with db.engine.begin() as conn:
                conn.execute(text(f"SET LOCAL lock_timeout = '{_FORENSIC_LOCK_TIMEOUT}'"))
                row = conn.execute(
                    text(
                        """
                        SELECT status, started_at FROM kb_index_jobs
                        WHERE id = :id
                        FOR UPDATE
                        """
                    ),
                    {"id": job_id},
                ).mappings().first()
                row_present = row is not None
                observed = dict(row) if row is not None else None
                conn.execute(text("DELETE FROM kb_index_jobs WHERE id = :id"), {"id": job_id})
                # After the job row, which references it.
                conn.execute(
                    text("DELETE FROM kb_documents WHERE id = :id"), {"id": document_id}
                )
                swept = True
        finally:
            if not swept:
                # The forensic FOR UPDATE above waits, and on a wedged foreign
                # session it raises — taking both DELETEs down with it, because
                # they share its transaction. That would leave the probe job
                # queued in a shared database with live workers on it, pointing
                # at a throwaway document that also survives. Sweep again on its
                # own transaction; the read has already had its chance.
                try:
                    with db.engine.begin() as conn:
                        conn.execute(
                            text(f"SET LOCAL lock_timeout = '{_FORENSIC_LOCK_TIMEOUT}'")
                        )
                        conn.execute(
                            text("DELETE FROM kb_index_jobs WHERE id = :id"), {"id": job_id}
                        )
                        conn.execute(
                            text("DELETE FROM kb_documents WHERE id = :id"), {"id": document_id}
                        )
                except Exception as exc:  # noqa: BLE001 — never mask the real error
                    warnings.warn(
                        "could not remove this test's probe rows "
                        f"(job {job_id}, document {document_id}): {exc}. They are "
                        "inert — the document is disabled and status='draft' — but "
                        "delete them by hand.",
                        stacklevel=2,
                    )
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

    # Foreign-claimer forensics — see the module docstring. Only reached when
    # neither thread got the probe job; a run in which one of them did cannot
    # have been stolen from, and drops straight through to the assertions.
    if job_id not in claimed:
        theft: str | None = None
        if not row_present:
            theft = "the probe row was already gone from kb_index_jobs"
        elif observed is not None and observed["status"] != "queued":
            theft = (
                f"the probe row was left status={observed['status']!r} "
                f"started_at={observed['started_at']!r}"
            )
        else:
            for idx, seen in enumerate(empty_handed):
                if seen is None:
                    continue
                if not seen["visible"]:
                    theft = f"claimer {idx} could not see the queued probe row at all"
                    break
                if not seen["lockable"]:
                    theft = (
                        f"claimer {idx} saw the queued probe row but its row lock "
                        "was held by a third session"
                    )
                    break
        if theft is not None:
            reason = (
                "kb_index_jobs worker contention: a foreign session claimed this "
                f"test's probe job {job_id} before either racing thread could, so "
                "SKIP LOCKED was never exercised and this run has no verdict. "
                f"Observed: {theft}; pre-race status was {pre_race_status!r}; the "
                f"two claimers returned {results}. This machine runs the live KB "
                "index workers (python -m worker) against the same Postgres and "
                "they poll this queue every 2s with the same FOR UPDATE SKIP "
                "LOCKED claim — see the module docstring. Re-run to get a verdict; "
                "do not stop the workers."
            )
            # Warn as well as skip: a warning survives `-q`, where a bare `s`
            # and an unread reason string look far too much like a pass.
            warnings.warn(reason, stacklevel=2)
            pytest.skip(reason)
        # Fall through: the row was present, queued and unlocked, and both
        # claimers still came back empty. Nothing foreign is implicated — that
        # is the defect this test exists to catch. Re-run with --showlocals to
        # read `empty_handed` and `observed`.

    assert len(claimed) == 1, f"expected exactly one claimer to win, got {results}"
    assert claimed[0] == job_id
    assert results.count(None) == 1
