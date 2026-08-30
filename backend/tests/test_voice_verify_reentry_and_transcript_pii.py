"""Two live-call gaps from the cycle-27 voice audit (G4-counter, G8).

**G4 (counter half).** ``_verify_identity_handler`` incremented
``state.verify_attempts`` without ever asking whether the caller was already
verified. Three re-entries — a model that re-asks for digits, an STT mishear the
caller corrects, a hop back through the verify node — routed a borrower who had
*already passed* verification to ``terminate_politely`` with a
``verification_failed`` handoff. A hang-up on a verified customer.

**G8.** ``append_transcript_turn`` wrote ``text_content`` raw while tool-call
args in the same module went through ``pii_redact``. DTMF keypad input and
spoken digits landed in ``interaction_transcript`` verbatim, undoing at rest the
care ``voice/bot.py`` takes to keep ``verify_identity`` args out of a browser.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

import db
from voice import persist
from voice import tools as voice_tools
from voice.session import VoiceSession


# ---------------------------------------------------------------------------
# G4 — a verified caller must not be hung up on by the attempt counter
# ---------------------------------------------------------------------------


def _verified_session() -> VoiceSession:
    session = VoiceSession(session_id="VS-REVERIFY1", customer_id="C1")
    session.interaction_id = "IX-REVERIFY1"
    session.identity_verified = True
    return session


def _build(session: VoiceSession):
    return voice_tools.build_tools(
        session,
        bot_id=None,
        start_recording=None,
        nodes={},
    )


def test_reverifying_a_verified_caller_costs_no_attempt() -> None:
    """The whole point: the counter does not move, so the cap is unreachable."""

    async def scenario():
        session = _verified_session()
        state, tools = _build(session)
        state.customer_name = "Asha Iyer"
        result, _next = await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "3210"}, None
        )
        return state, result

    state, result = asyncio.run(scenario())

    assert result["ok"] is True, result
    assert result["alreadyVerified"] is True
    assert result["verified"] is True
    assert result["customerName"] == "Asha Iyer"
    assert result["say"], "the model needs a directive or it says nothing"
    assert state.verify_attempts == 0, "a verified caller burned a verification attempt"


def test_a_verified_caller_never_reaches_the_handoff_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Four re-entries — one past the cap — and still no handoff, no terminate.

    Guards the exact production shape: the caller *is* verified, and every
    subsequent call would previously have moved the counter toward 3.
    """
    handoffs: list[dict] = []
    monkeypatch.setattr(persist, "record_handoff", lambda **kw: handoffs.append(kw))

    def _boom(**_kw):  # pragma: no cover - only runs if the guard is gone
        raise AssertionError("verified caller was sent through the lookup path")

    monkeypatch.setattr(persist, "lookup_customer_for_verify", _boom)

    async def scenario():
        session = _verified_session()
        state, tools = _build(session)
        nodes = []
        for _ in range(4):
            _result, next_node = await tools["verify_identity"].handler(
                {"method": "phone_match", "value": "3210"}, None
            )
            nodes.append(next_node)
        return state, nodes

    state, nodes = asyncio.run(scenario())

    assert state.verify_attempts == 0
    assert handoffs == [], "a verified caller was queued for a verification_failed handoff"
    # _node() returns None for a name the graph never registered; what matters
    # is that terminate_politely is not the landing.
    assert all(n is None or n.get("name") != "terminate_politely" for n in nodes), nodes


def test_the_guard_needs_both_the_flag_and_a_bound_customer() -> None:
    """``identity_verified`` without a customer id is not a verified caller.

    A half-bound session must fall through to the real verification path rather
    than answer "you're already verified" on the strength of a stale flag.
    """

    async def scenario():
        session = VoiceSession(session_id="VS-HALFBOUND", customer_id=None)
        session.interaction_id = "IX-HALFBOUND"
        session.identity_verified = True
        _state, tools = _build(session)
        # An unsupported method proves we got past the guard into normalisation.
        return await tools["verify_identity"].handler({"method": "vibes", "value": "x"}, None)

    result, _next = asyncio.run(scenario())
    assert result.get("error") == "unsupported_method", result


def test_unverified_path_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must be invisible to every caller who has not verified yet."""
    monkeypatch.setattr(persist, "lookup_customer_for_verify", lambda **_kw: None)
    recorded: list[dict] = []
    monkeypatch.setattr(
        persist, "record_identity_verification", lambda **kw: recorded.append(kw)
    )

    async def scenario():
        session = VoiceSession(session_id="VS-UNVERIF02", customer_id=None)
        session.interaction_id = "IX-UNVERIF02"
        state, tools = _build(session)
        result, _next = await tools["verify_identity"].handler(
            {"method": "phone_match", "value": "3210"}, None
        )
        return state, result

    state, result = asyncio.run(scenario())

    assert state.verify_attempts == 1, "the unverified path stopped counting attempts"
    assert result["ok"] is False
    assert result["error"] == "no_match"
    assert result["remaining"] == 2
    assert recorded and recorded[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# G8 — transcript turns are redacted before they are stored
# ---------------------------------------------------------------------------


@pytest.fixture
def interaction(db_tx) -> str:
    ix = f"IX-PII-{uuid.uuid4().hex[:8].upper()}"
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel,
               status, started_at)
            VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots LIMIT 1),
                    'voice', 'active', now() - interval '5 minutes')
            """
        ),
        {"id": ix, "t": db.TENANT_ID, "c": customer},
    )
    return ix


def _stored(db_tx, interaction_id: str, turn_index: int) -> str:
    return db_tx.execute(
        text(
            "SELECT text FROM interaction_transcript "
            "WHERE interaction_id = :ix AND turn_index = :ti"
        ),
        {"ix": interaction_id, "ti": turn_index},
    ).scalar()


def test_keypad_digits_do_not_survive_in_the_transcript(db_tx, interaction: str) -> None:
    """``voice/ivr.py`` folds DTMF in as plain text; it must not persist raw."""
    persist.append_transcript_turn(
        interaction_id=interaction,
        turn_index=1,
        speaker="customer",
        text_content="Caller keypad input: 9876543210",
        at_sec=12,
    )
    stored = _stored(db_tx, interaction, 1)
    assert "9876543210" not in stored, stored
    assert "98765432" not in stored, stored
    assert stored.startswith("Caller keypad input: "), "the turn lost its context"


def test_formatted_pii_goes_through_the_shared_redactor(db_tx, interaction: str) -> None:
    """Same detectors the tool-call audit rows use — card, phone, account."""
    persist.append_transcript_turn(
        interaction_id=interaction,
        turn_index=2,
        speaker="customer",
        text_content="my card is 4111 1111 1111 1111 and my number is +91 98765 43210",
        at_sec=20,
    )
    stored = _stored(db_tx, interaction, 2)
    assert "4111 1111 1111" not in stored, stored
    assert "98765 43210" not in stored, stored
    assert "**** **** ****" in stored, stored


def test_ordinary_speech_is_not_mangled(db_tx, interaction: str) -> None:
    """Redaction that damages normal turns would break QA scoring and export.

    Note the amount and the short tail: four digits are what verification itself
    asks for, and an amount is the substance of a collections call. Neither is
    an identifier and neither may be touched.
    """
    body = "I can pay 5000 on the 12th, the last four of my account are 3210, sorry for the delay"
    persist.append_transcript_turn(
        interaction_id=interaction,
        turn_index=3,
        speaker="customer",
        text_content=body,
        at_sec=30,
    )
    assert _stored(db_tx, interaction, 3) == body


def test_redaction_helper_matches_the_stored_value(db_tx, interaction: str) -> None:
    """The row is exactly what the helper produces — no second transformation."""
    body = "Caller keypad input: 9876543210"
    persist.append_transcript_turn(
        interaction_id=interaction,
        turn_index=4,
        speaker="customer",
        text_content=body,
        at_sec=40,
    )
    assert _stored(db_tx, interaction, 4) == persist._redact_transcript_text(body)
