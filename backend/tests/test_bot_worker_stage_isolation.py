"""One poison row must not silently stop every queue below it.

``process_one_any`` used to guard four of twelve stages, with five unguarded
ones running *above* the guarded ones. A persistently-raising
``whatsapp_outbound`` aborted the tick before the closer, cadence, campaigns,
treatment and webhooks were reached. The loop logged ``process_one crashed —
backing off`` with no queue name, slept 1.5s, and repeated forever.

WP-018 wraps every stage. This file injects a raise into stage 1 and asserts
stage 12 still ran, and that the log named the queue that failed.
"""

from __future__ import annotations

import logging

import pytest


def test_a_poison_row_in_stage_1_does_not_prevent_stage_12(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import agent_core.clerk as clerk_mod
    import bot_jobs
    import cadence
    import call_closer
    import campaigns
    import payment_events
    import promise_fulfillment
    import webhooks_dispatch
    import whatsapp_outbound
    from agent_core.treatment import enact as treatment_enact
    from agent_core.treatment import followthrough as treatment_followthrough
    from agent_core.treatment import sweep as treatment_sweep

    import bot_worker

    ran: list[str] = []

    def _poison(*_a: object, **_k: object) -> bool:
        ran.append("whatsapp_outbound")
        raise RuntimeError("poison row")

    def _idle(name: str):
        def _fn(*_a: object, **_k: object) -> bool:
            ran.append(name)
            return False

        return _fn

    def _late(*_a: object, **_k: object) -> bool:
        ran.append("bot_jobs")
        return True

    monkeypatch.setattr(bot_jobs, "bot_runtime_enabled", lambda: True)
    monkeypatch.setattr(whatsapp_outbound, "process_one", _poison)
    monkeypatch.setattr(promise_fulfillment, "process_one_reminder", _idle("promise_reminders"))
    monkeypatch.setattr(payment_events, "process_one_voice", _idle("bounce_voice"))
    monkeypatch.setattr(call_closer, "process_one", _idle("call_closer"))
    monkeypatch.setattr(cadence, "process_one", _idle("cadence"))
    monkeypatch.setattr(campaigns, "process_one", _idle("campaigns"))
    monkeypatch.setattr(treatment_enact, "process_one", _idle("treatment_enact"))
    monkeypatch.setattr(treatment_followthrough, "process_one", _idle("treatment_followthrough"))
    monkeypatch.setattr(treatment_sweep, "process_one", _idle("treatment_sweep"))
    monkeypatch.setattr(webhooks_dispatch, "process_one", _idle("webhooks_dispatch"))
    monkeypatch.setattr(clerk_mod, "process_one", _idle("clerk"))
    monkeypatch.setattr(bot_jobs, "process_one", _late)

    previous = bot_worker._iteration
    # After increment: 2. Not a bot-first tick, not a settle tick, so the
    # twelve drains run in order and stage 1 is whatsapp_outbound.
    bot_worker._iteration = 1
    try:
        with caplog.at_level(logging.ERROR, logger="bot_worker"):
            did = bot_worker.process_one_any()
    finally:
        bot_worker._iteration = previous

    assert did is True
    assert ran == [
        "whatsapp_outbound",
        "promise_reminders",
        "bounce_voice",
        "call_closer",
        "cadence",
        "campaigns",
        "treatment_enact",
        "treatment_followthrough",
        "treatment_sweep",
        "webhooks_dispatch",
        "clerk",
        "bot_jobs",
    ]
    assert "process_one crashed" not in caplog.text
    assert "queue=whatsapp_outbound" in caplog.text
