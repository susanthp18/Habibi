"""Phase-1 latency defects from the five-reviewer audit in ``latency_review/``.

Each test pins one defect that was a real code fault rather than a tuning
choice, so none of them needs a measured baseline to be meaningful.
"""

from __future__ import annotations


# --------------------------------------------- retrieval-log flush is off-path


def test_retrieval_log_flush_leaves_the_retrieval_thread():
    """``record_retrieval_log`` runs on the worker thread doing the KB
    retrieval, inside the window the turn is waiting on. Draining the buffer
    there meant one turn in N paid a synchronous executemany INSERT."""
    import threading

    import kb_retrieve

    caller = threading.current_thread().name
    flushed = threading.Event()
    seen: list[str] = []

    def fake_write(rows):
        seen.append(threading.current_thread().name)
        flushed.set()

    real_write = kb_retrieve._write_retrieval_logs
    real_enabled = kb_retrieve._log_buffering_enabled
    try:
        kb_retrieve._write_retrieval_logs = fake_write
        kb_retrieve._log_buffering_enabled = lambda: True
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_flush_pending = False
        kb_retrieve._log_last_flush = 0.0  # force "due"

        kb_retrieve.record_retrieval_log({"id": "r1"}, defer=True)
        assert flushed.wait(timeout=5), "flush never ran"
    finally:
        kb_retrieve._write_retrieval_logs = real_write
        kb_retrieve._log_buffering_enabled = real_enabled
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()

    assert seen and seen[0] != caller, "the flush still ran on the caller's thread"
    assert seen[0].startswith("kb-retrieval-log")


def test_retrieval_log_buffer_is_bounded():
    """The flush is off-thread now, so a dead database backs rows up here
    instead of blocking the caller. These are analytics: drop, do not grow."""
    import kb_retrieve

    real_enabled = kb_retrieve._log_buffering_enabled
    try:
        kb_retrieve._log_buffering_enabled = lambda: True
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_buffer.extend(
                {"id": str(i)} for i in range(kb_retrieve._LOG_BUFFER_MAX_ROWS)
            )
            kb_retrieve._log_flush_pending = True  # suppress the real flush
        kb_retrieve.record_retrieval_log({"id": "newest"}, defer=True)

        with kb_retrieve._log_lock:
            assert len(kb_retrieve._log_buffer) == kb_retrieve._LOG_BUFFER_MAX_ROWS
            assert kb_retrieve._log_buffer[-1]["id"] == "newest"
            assert kb_retrieve._log_buffer[0]["id"] == "1", "dropped the wrong end"
    finally:
        kb_retrieve._log_buffering_enabled = real_enabled
        with kb_retrieve._log_lock:
            kb_retrieve._log_buffer.clear()
            kb_retrieve._log_flush_pending = False
