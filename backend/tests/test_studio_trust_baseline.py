"""Agent Studio trust baseline — canary, shadow, handoff, skills, evals, chain."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

import db
from agent_core import change_log
from agent_core.guardrails import evaluate_guardrails
from agent_core.tools.catalog import CATALOG


CATALOG_NAMES = set(CATALOG.specs)


def _experiment(**over):
    base = {
        "id": "EXP-1",
        "canary_deployment_id": "DEP-CANARY",
        "baseline_deployment_id": "DEP-BASE",
        "traffic_pct": 100,
        "shadow": False,
    }
    return {**base, **over}


def test_whatsapp_does_not_flag_missing_recording_disclosure() -> None:
    kwargs = dict(
        customer_text="hello",
        bot_text="Please pay your overdue EMI.",
        intent="payment_intent",
        guardrails={"alwaysDiscloseRecording": True},
        turn_index=1,
        elapsed_seconds=2.0,
        customer_bot_exchanges=1,
        recording_disclosed=False,
    )
    voice = evaluate_guardrails(channel="voice", **kwargs)
    text_ch = evaluate_guardrails(channel="whatsapp", **kwargs)
    assert "missing-recording-disclosure" in voice
    assert "missing-recording-disclosure" not in text_ch


def test_the_channel_actually_reaches_the_guardrail_from_the_turn_writer(db_tx) -> None:
    """The gate above was green while the live path was broken.

    `evaluate_and_flag_bot_turn` accepted `channel`, used it for `TurnFacts`,
    and did not forward it to `evaluate_guardrails` — so every WhatsApp turn
    defaulted to "voice" and wrote an `r-rec` RBI recording-disclosure
    violation for a disclosure `prompt.py` forbids the bot from saying on text.
    Testing the gate directly could never catch that; this goes through the
    caller. The flag writes below fail on a synthetic interaction id and are
    swallowed by the function's own handlers, which is why no fixture is needed.
    """
    from voice.persist import evaluate_and_flag_bot_turn

    kwargs = dict(
        interaction_id="INT-CHANNEL-WIRING-PROBE",
        customer_text="hello",
        bot_text="Please pay your overdue EMI.",
        intent="payment_intent",
        guardrails={"alwaysDiscloseRecording": True},
        turn_index=1,
        elapsed_seconds=2.0,
        customer_bot_exchanges=1,
        recording_disclosed=False,
        simulated=True,
    )

    assert "missing-recording-disclosure" in evaluate_and_flag_bot_turn(
        channel="voice", **kwargs
    )
    assert "missing-recording-disclosure" not in evaluate_and_flag_bot_turn(
        channel="whatsapp", **kwargs
    )


def test_two_bots_can_append_concurrently_without_breaking_the_chain(db_real) -> None:
    tenant = db.current_tenant()
    actor = db._actor_user_id()
    bots = [f"chain-conc-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    for bot_id in bots:
        db_real.track("audit_log", entity_id=bot_id)

    errors: list[BaseException] = []

    def _write(bot_id: str) -> None:
        try:
            with db.engine.begin() as conn:
                change_log.record_archive(
                    conn,
                    tenant_id=tenant,
                    actor_user_id=actor,
                    entry_id=db._id("AUD"),
                    bot_id=bot_id,
                    retired_deployment_id=None,
                )
        except BaseException as exc:  # noqa: BLE001 — surface into the parent
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_write, bots))
    assert not errors, errors

    with db.engine.connect() as conn:
        verdict = change_log.verify_chain(conn, tenant_id=tenant)
        rows = list(
            conn.execute(
                text(
                    """
                    SELECT payload->>'seq' AS seq FROM audit_log
                     WHERE tenant_id = :t AND entity_type = 'bot'
                       AND entity_id IN (:b0, :b1)
                    """
                ),
                {"t": tenant, "b0": bots[0], "b1": bots[1]},
            )
        )
    assert verdict["ok"] is True, verdict
    seqs = [int(r[0]) for r in rows]
    assert len(seqs) == 2
    assert seqs[0] != seqs[1]


