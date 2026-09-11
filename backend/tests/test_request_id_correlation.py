"""The request id follows the work: into the log line, and onto the job row."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

import request_context


def test_text_log_lines_carry_the_request_id() -> None:
    from observability import RedactingTextFormatter

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    token = request_context.set_request_id("req-abc123")
    try:
        line = RedactingTextFormatter().format(record)
    finally:
        request_context.reset_request_id(token)
    assert "[req-abc123]" in line
    bare = RedactingTextFormatter().format(
        logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    )
    assert "[-]" in bare


def test_a_work_runtime_job_records_the_request_that_made_it(db_tx) -> None:
    import db
    from work_runtime import start_workflow

    token = request_context.set_request_id("req-job-1")
    try:
        job = start_workflow(
            workflow_type="bounce_chase",
            payload={},
            customer_id=None,
            idempotency_key="req-id-test:bounce_chase:1",
        )
    finally:
        request_context.reset_request_id(token)
    rid = db_tx.execute(
        text("SELECT request_id FROM work_runtime_jobs WHERE id = :id"), {"id": job["id"]}
    ).scalar()
    assert rid == "req-job-1"
    assert db.current_tenant()


def test_a_job_minted_outside_a_request_has_no_id(db_tx) -> None:
    from work_runtime import start_workflow

    assert request_context.get_request_id() is None
    job = start_workflow(
        workflow_type="bounce_chase",
        payload={},
        customer_id=None,
        idempotency_key="req-id-test:bounce_chase:2",
    )
    rid = db_tx.execute(
        text("SELECT request_id FROM work_runtime_jobs WHERE id = :id"), {"id": job["id"]}
    ).scalar()
    assert rid is None
