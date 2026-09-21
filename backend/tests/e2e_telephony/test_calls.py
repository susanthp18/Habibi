"""End-to-end Asterisk calls. Each test names the finding it closes
(docs/design/asterisk-telephony-findings.md)."""

from __future__ import annotations

import io
import time
import wave

import pytest

from tests.e2e_telephony.conftest import (
    AGENT,
    CUSTOMER,
    Call,
    attempt_row,
    pbx,
    phone,
    sql,
    transcript,
    wait_for,
)

TERMINAL = {"completed", "busy", "no_answer", "rejected", "failed", "invalid_number", "canceled", "transferred"}


def test_an_inbound_call_reaches_the_bot_and_everything_is_kept() -> None:
    """B1-B5, F1, F4, F5, F8: connects, knows the caller, keeps the keypress, the
    session row and the recording."""
    call = Call("borrower")
    call.wait_ended()
    ix = call.interaction()

    row = sql("SELECT direction FROM interactions WHERE id = :ix", ix=ix)[0]
    assert row["direction"] == "inbound"
    session = sql("SELECT transport FROM voice_sessions WHERE provider_call_id = :sid", sid=call.sip_id)[0]
    assert session["transport"] == "asterisk"

    turns = transcript(ix)
    said = " ".join(t["text"].lower() for t in turns if t["speaker"] == "customer")
    assert "payment" in said, turns
    assert any(t["speaker"] == "bot" for t in turns)
    # The aggregator's own prefix, not a bare "1": that matched almost any
    # transcript and would have passed with the keypad path switched off.
    assert "keypad input" in said, f"keypress missing from {turns}"

    media = wait_for(
        lambda: sql("SELECT size_bytes FROM interaction_media WHERE interaction_id = :ix AND kind = 'sip_audio'", ix=ix),
        timeout=60,
        what="the Asterisk recording to be stored",
    )
    assert media[0]["size_bytes"] > 10_000

    # What the caller heard is intelligible speech at the right rate.
    import azure_speech

    with wave.open(io.BytesIO(call.heard())) as w:
        rate, frames = w.getframerate(), w.readframes(w.getframerate() * 8)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    heard = azure_speech.transcribe(buf.getvalue(), content_type=f"audio/wav; codecs=audio/pcm; samplerate={rate}")
    assert len((heard.get("text") or "").split()) >= 3, heard


def test_an_outbound_call_is_about_the_borrower_and_completes(dial) -> None:
    """F1, F2: the bot knows the attempt; the attempt reaches a final state."""
    placed = dial("talk")
    assert placed["result"]["placed"] is True, placed
    attempt_id = placed["attempt"]["id"]
    sip_id = placed["result"]["callSid"]
    assert sip_id == f"att-{attempt_id}"

    seen: list[str] = []

    def done() -> bool:
        state = attempt_row(attempt_id)["state"]
        if not seen or seen[-1] != state:
            seen.append(state)
        return state in TERMINAL

    wait_for(done, timeout=150, every=1, what="the outbound attempt to finish")
    row = attempt_row(attempt_id)
    assert row["state"] == "completed", seen
    assert "answered" in seen or "live" in seen or "ringing" in seen, seen
    assert row["provider"] == "asterisk" and row["provider_call_id"] == sip_id
    assert row["talk_sec"], row

    ix = sql("SELECT interaction_id FROM voice_sessions WHERE provider_call_id = :sid", sid=sip_id)[0]["interaction_id"]
    interaction = sql("SELECT direction, customer_id FROM interactions WHERE id = :ix", ix=ix)[0]
    assert interaction == {"direction": "outbound", "customer_id": CUSTOMER}


@pytest.mark.parametrize("mode, state", [("busy", "busy"), ("reject", "rejected"), ("noanswer", "no_answer")])
def test_an_outbound_call_that_is_not_answered_says_why(dial, mode: str, state: str) -> None:
    """F2: busy and unanswered attempts used to sit at `dialing` forever."""
    placed = dial(mode)
    attempt_id = placed["attempt"]["id"]
    wait_for(
        lambda: attempt_row(attempt_id)["state"] in TERMINAL,
        timeout=90,
        what=f"the {mode} attempt to finish",
    )
    assert attempt_row(attempt_id)["state"] == state


def test_the_caller_hanging_up_ends_the_call_for_the_bot_too(dial) -> None:
    """ARI sends StasisEnd and no ChannelDestroyed once a leg leaves the app. The
    controller waited for the latter, so a caller who hung up first left the bot
    running -- two minutes of model calls to nobody on a live call -- and the
    attempt never reached a final state."""
    phone("POST", "/asterisk/variable", query={"variable": "BORROWER_MODE", "value": "hangup"})
    placed = dial("hangup")
    attempt_id = placed["attempt"]["id"]

    wait_for(
        lambda: attempt_row(attempt_id)["state"] in TERMINAL,
        timeout=90,
        what="the attempt to finish after the caller hung up",
    )
    assert attempt_row(attempt_id)["state"] == "completed"
    # Nothing of this call is left running on the PBX.
    wait_for(
        lambda: not [c for c in pbx("GET", "/channels") if c["id"].startswith(f"att-{attempt_id}")],
        timeout=30,
        what="the bot's leg to be released",
    )

    # And nothing is still being *paid for*. The orphaned leg went on thinking
    # and speaking for two minutes after the caller left: 14 LLM calls and 15
    # TTS calls billed to a dead line. Teardown alone would not have caught it.
    ended = attempt_row(attempt_id)["ended_at"]
    ix = sql(
        "SELECT interaction_id FROM voice_sessions WHERE provider_call_id = :sid",
        sid=f"att-{attempt_id}",
    )[0]["interaction_id"]
    time.sleep(20)
    late = sql(
        """
        SELECT service_id, occurred_at FROM usage_events
        WHERE interaction_id = :ix AND occurred_at > :ended + interval '5 seconds'
        """,
        ix=ix,
        ended=ended,
    )
    assert late == [], f"model usage billed after the caller hung up: {late}"


def test_an_unroutable_extension_fails_readably() -> None:
    """F11: a clean reason, not a raw ARI body."""
    import db
    import outbound

    with db.engine.begin() as conn:
        attempt = outbound.reserve(
            conn, customer_id=CUSTOMER, to_phone="1999", objective="dpd_reminder",
            context={"source": "telephony_e2e"},
        )
    result = outbound.place(db.engine, attempt, to_phone="1999")
    assert result == {"placed": False, "state": "failed", "reason": "dial_failed", "attemptId": attempt["id"]}
    row = attempt_row(attempt["id"])
    assert row["provider_error"].startswith("dial_failed: ari ")
    assert "{" not in row["provider_error"]
    # A failure before the carrier answered is still an Asterisk attempt.
    assert row["provider"] == "asterisk"


def test_audio_keeps_flowing_while_the_bot_is_silent() -> None:
    """F6: the PBX sent no RTP between bot utterances."""
    call = Call("silent")
    # Past the greeting, before any dead-air nudge.
    time.sleep(10)
    first = pbx("GET", f"/channels/{call.sip_id}/rtp_statistics")["txcount"]
    time.sleep(3)
    second = pbx("GET", f"/channels/{call.sip_id}/rtp_statistics")["txcount"]
    phone("DELETE", f"/channels/{call.phone_channel}")
    # 20 ms packets: three seconds is ~150; allow for jitter.
    assert second - first >= 120, (first, second)


def test_asking_for_a_person_reaches_an_agent() -> None:
    """F3, N6: "I want to speak to a human agent" ends at a ringing, answered agent."""
    phone("POST", "/asterisk/variable", query={"variable": "AGENT_ANSWERED", "value": ""})
    call = Call("human")
    answered = wait_for(
        lambda: phone("GET", "/asterisk/variable", query={"variable": "AGENT_ANSWERED"}).get("value"),
        timeout=60,
        what=f"agent {AGENT} to be rung and answer",
    )
    assert answered
    ix = call.interaction()
    assert sql("SELECT 1 FROM interaction_handoffs WHERE interaction_id = :ix", ix=ix)
    phone("DELETE", f"/channels/{call.phone_channel}")


def test_speech_over_the_greeting_is_kept() -> None:
    """N3: the caller's first words used to be dropped by the greeting mute."""
    call = Call("bargein")
    ix = call.interaction()
    wait_for(
        lambda: any(
            t["speaker"] == "customer" and "late" in t["text"].lower() for t in transcript(ix)
        ),
        timeout=40,
        what="the words spoken over the greeting to reach the transcript",
    )
    phone("DELETE", f"/channels/{call.phone_channel}")


def test_a_keypress_alone_gets_answered() -> None:
    """A digits-only entry must open a user turn and get a reply.

    The ``borrower`` script also presses a key, but it speaks 8 seconds later,
    so the digits are folded into that spoken turn -- it passes whether or not
    the keypress was ever answered on its own. This script says nothing at all,
    so the only thing that can produce a bot turn after the digit is a real
    keypad turn. Before the keypad start strategy the caller heard silence here
    until the idle ladder fired.
    """
    call = Call("keypad")
    ix = call.interaction()

    def answered() -> bool:
        turns = transcript(ix)
        pressed = next(
            (t["turn_index"] for t in turns
             if t["speaker"] == "customer" and "keypad" in t["text"].lower()),
            None,
        )
        if pressed is None:
            return False
        return any(t["speaker"] == "bot" and t["turn_index"] > pressed for t in turns)

    wait_for(
        answered,
        timeout=20,
        what="the bot to answer a keypress the caller never spoke over",
    )
    phone("DELETE", f"/channels/{call.phone_channel}")


def test_three_calls_at_once() -> None:
    """Three concurrent calls each get their own bot session and record."""
    # Started one after another so each finds its own PBX leg; they overlap for
    # most of their length.
    calls = [Call("silent") for _ in range(3)]
    try:
        assert len({c.sip_id for c in calls}) == 3
        assert len({c.interaction() for c in calls}) == 3
    finally:
        for c in calls:
            phone("DELETE", f"/channels/{c.phone_channel}")
