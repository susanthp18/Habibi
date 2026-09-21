"""source-db ingest must wait when the kb worker already owns a job."""

from __future__ import annotations

import pytest

import kb_ingest


class _Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Engine:
    def connect(self):
        return _Conn()


def test_wait_for_index_jobs_polls_while_worker_still_running(monkeypatch: pytest.MonkeyPatch) -> None:
    reads = [
        {"a": "succeeded", "b": "running"},
        {"a": "succeeded", "b": "succeeded"},
    ]

    def _statuses(_conn, job_ids):
        return reads.pop(0)

    slept: list[float] = []
    ticks = iter([0.0, 0.4])

    monkeypatch.setattr(kb_ingest, "job_statuses", _statuses)
    out = kb_ingest.wait_for_index_jobs(
        _Engine(),
        ["a", "b"],
        timeout_s=5,
        poll_s=0.4,
        sleeper=slept.append,
        clock=lambda: next(ticks, 0.8),
    )
    assert out == {"a": "succeeded", "b": "succeeded"}
    assert slept == [0.4]
    assert reads == []


def test_wait_for_index_jobs_fails_on_failed_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kb_ingest, "job_statuses", lambda *_a, **_k: {"a": "succeeded", "b": "failed"}
    )
    with pytest.raises(RuntimeError, match="did not succeed"):
        kb_ingest.wait_for_index_jobs(_Engine(), ["a", "b"], sleeper=lambda _s: None)


def test_wait_for_index_jobs_times_out_if_still_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kb_ingest, "job_statuses", lambda *_a, **_k: {"a": "running"}
    )
    with pytest.raises(RuntimeError, match="still in flight"):
        kb_ingest.wait_for_index_jobs(
            _Engine(),
            ["a"],
            timeout_s=0,
            poll_s=0.1,
            sleeper=lambda _s: None,
            clock=lambda: 0.0,
        )
