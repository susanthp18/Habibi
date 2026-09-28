"""The master outbound switch: off by default, and off means nothing dials.

This guards one failure: telephoning a real person who did not ask to be
called. So the tests are written the pessimistic way round — the interesting
assertions are all that dialling did *not* happen, including when the switch
machinery itself is broken.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import platform_switches


@pytest.fixture(autouse=True)
def _clear_switch_cache():
    """The reader caches for a couple of seconds; tests must not inherit it."""
    platform_switches.invalidate()
    yield
    platform_switches.invalidate()


# --- the default ------------------------------------------------------------


def test_outbound_is_off_when_no_row_exists(db_tx) -> None:
    """A fresh install must not dial. Absence is off, not unset."""
    db_tx.execute(
        text("DELETE FROM platform_switches WHERE key = :k"),
        {"k": platform_switches.OUTBOUND_ENABLED},
    )
    platform_switches.invalidate()
    assert platform_switches.outbound_enabled() is False


def test_an_unreadable_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """A database we cannot reach is not permission to start calling people.

    The usual instinct — degrade gracefully, assume the feature is on — is
    exactly wrong here: the graceful failure is silence.
    """

    class _Boom:
        def connect(self):
            raise RuntimeError("database on fire")

    monkeypatch.setattr(platform_switches, "_TTL_SECONDS", 0.0)
    platform_switches.invalidate()
    assert platform_switches.is_enabled("outbound.enabled", engine=_Boom()) is False


def test_the_switch_reads_back_what_was_written(db_tx) -> None:
    platform_switches.set_enabled(db_tx, platform_switches.OUTBOUND_ENABLED, True)
    platform_switches.invalidate()
    row = db_tx.execute(
        text("SELECT enabled FROM platform_switches WHERE key = :k"),
        {"k": platform_switches.OUTBOUND_ENABLED},
    ).scalar()
    assert row is True

    platform_switches.set_enabled(db_tx, platform_switches.OUTBOUND_ENABLED, False)
    row = db_tx.execute(
        text("SELECT enabled FROM platform_switches WHERE key = :k"),
        {"k": platform_switches.OUTBOUND_ENABLED},
    ).scalar()
    assert row is False


def test_an_unknown_key_is_refused_not_created(db_tx) -> None:
    """A typo in a URL must not mint a switch that nothing reads."""
    with pytest.raises(KeyError):
        platform_switches.set_enabled(db_tx, "outbound.enabledd", True)
    n = db_tx.execute(
        text("SELECT count(*) FROM platform_switches WHERE key = 'outbound.enabledd'")
    ).scalar()
    assert n == 0


def test_flipping_the_switch_is_recorded(db_tx) -> None:
    """A kill switch with no attribution is an argument waiting to happen."""
    platform_switches.set_enabled(db_tx, platform_switches.OUTBOUND_ENABLED, True)
    row = (
        db_tx.execute(
            text(
                "SELECT label, actor_user_id FROM activity_events"
                " WHERE kind = 'platform_switch_changed' AND entity_id = :k"
                " ORDER BY at DESC LIMIT 1"
            ),
            {"k": platform_switches.OUTBOUND_ENABLED},
        )
        .mappings()
        .first()
    )
    assert row is not None
    assert "on" in row["label"].lower()
    assert row["actor_user_id"]


def test_every_known_switch_is_listed_even_when_never_flipped(db_tx) -> None:
    """A screen that showed nothing until someone flipped something would be
    lying about the default."""
    db_tx.execute(text("DELETE FROM platform_switches"))
    listed = platform_switches.get_all(db_tx)
    keys = {s["key"] for s in listed}
    assert platform_switches.OUTBOUND_ENABLED in keys
    assert all(s["enabled"] is False for s in listed)


# --- the gate at the carrier boundary ---------------------------------------


def test_the_carrier_call_is_refused_while_the_switch_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate lives in the one function that reaches Twilio.

    Placed at the call sites instead, it would be three checks that a fourth
    caller could forget. Here, a bypass has to be written into this file.
    """
    from voice import twilio_ops

    monkeypatch.setattr(platform_switches, "outbound_enabled", lambda **_k: False)

    def _explode(*_a, **_k):
        raise AssertionError("the carrier client must not be reached")

    monkeypatch.setattr(twilio_ops, "rest_client", _explode)

    with pytest.raises(twilio_ops.OutboundDisabled):
        twilio_ops.start_outbound_call(to="919655282324")


def test_the_refusal_is_its_own_exception_type() -> None:
    """Callers have to tell "we declined" apart from "the carrier refused"."""
    from voice import twilio_ops

    assert issubclass(twilio_ops.OutboundDisabled, RuntimeError)


def test_place_suppresses_rather_than_failing_when_the_switch_is_off(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dial we declined to make is not a dial that went unanswered.

    Recording it as `failed` would quietly deflate answer rate — the metric the
    whole outbound operation is judged on — every time the switch was off.

    Note where the refusal is discovered: `place` does not pre-flight the
    switch, it lets the carrier boundary raise and translates the result. One
    place decides whether a dial is permitted; a second check here would be a
    second thing to keep in agreement with it.
    """
    import db
    import outbound
    from voice import twilio_ops

    def _refuse(**_kwargs):
        raise twilio_ops.OutboundDisabled("outbound_disabled")

    monkeypatch.setattr(twilio_ops, "start_outbound_call", _refuse)
    monkeypatch.setattr(twilio_ops, "twilio_phone", lambda: "+15550000000")

    row = (
        db_tx.execute(
            text("SELECT id, tenant_id FROM customers WHERE id <> 'UNKNOWN-CALLER' LIMIT 1")
        )
        .mappings()
        .first()
    )
    if row is None:
        pytest.skip("no seeded customer")
    attempt = outbound.reserve(
        db_tx,
        customer_id=row["id"],
        to_phone="919655282324",
        objective="kill_switch_test",
    )
    assert attempt is not None

    result = outbound.place(db.engine, attempt, to_phone="919655282324")

    assert result["placed"] is False
    assert result["reason"] == "outbound_disabled"
    assert result["state"] == outbound.STATE_SUPPRESSED

    state = db_tx.execute(
        text("SELECT state FROM call_attempts WHERE id = :id"), {"id": attempt["id"]}
    ).scalar()
    assert state == outbound.STATE_SUPPRESSED, "a declined dial must not read as failed"


def test_place_never_raises_when_the_switch_refusal_cannot_be_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`place` promises never to raise, and the refusal path is no exception.

    A throw here would strand the attempt in `dialing` with nothing to reclaim
    it — the silent strand `cadence` already had to grow a recovery path for.
    """
    import outbound
    from voice import twilio_ops

    def _refuse(**_kwargs):
        raise twilio_ops.OutboundDisabled("outbound_disabled")

    monkeypatch.setattr(twilio_ops, "start_outbound_call", _refuse)
    monkeypatch.setattr(twilio_ops, "twilio_phone", lambda: "+15550000000")
    # Past the fleet gate, then a store that cannot record the refusal.
    monkeypatch.setattr(outbound, "in_flight_count", lambda *_a, **_k: 0)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, *_a, **_k):
            raise RuntimeError("cannot write")

    class _Engine:
        def begin(self):
            return _Conn()

    result = outbound.place(
        _Engine(),
        {"id": "OBA-TEST-2", "tenantId": "tenant-bigbound"},
        to_phone="919655282324",
    )
    assert result["placed"] is False
    assert result["reason"] == "outbound_disabled"


# --- the demo dial's objective ----------------------------------------------


# --- the demo window override, and its limits -------------------------------


def test_the_window_override_is_off_by_default(db_tx) -> None:
    db_tx.execute(
        text("DELETE FROM platform_switches WHERE key = :k"),
        {"k": platform_switches.DEMO_IGNORES_WINDOW},
    )
    platform_switches.invalidate()
    assert platform_switches.demo_ignores_window() is False


# --- offers on an outbound mission ------------------------------------------


def _card_with_offers(offers: list[str]):
    """A real card, with the objective's offer permission swapped."""
    import db
    import mission as mission_mod

    card = mission_mod.card_for_bot(str(db.DEFAULT_BOT_ID))
    for spec in card.outbound.objectives:
        spec.allowed_offers = list(offers)
    return card


def test_an_objective_with_offers_does_not_prohibit_cross_sell(db_tx) -> None:
    """Permission flows card -> mission -> brief, and the latch reads the mission.

    `voice/bot.py` sets a hard `upsell_blocked` latch on `allowedOffers == []`,
    described there as blocking a pitch "by any route, prompt included". So an
    empty list is not a hint to the model, it is an interlock — and the only
    thing that lifts it is the card saying otherwise.
    """
    import mission as mission_mod

    card = _card_with_offers(["topup-loan", "gold-loan"])
    built = mission_mod.build(
        db_tx,
        customer_id="cust-susanth",
        objective="dpd_reminder",
        account_id="AC-SUSANTH",
        card=card,
        bot_id="kaia-v2-4",
    )
    assert built["allowedOffers"] == ["topup-loan", "gold-loan"]
    assert "cross_sell" not in built["prohibited"]
    assert built["allowedOffers"] != [], "an empty list would re-arm the upsell latch"

    brief = mission_mod.briefing(built)
    assert "Do NOT mention any product" not in brief


def test_an_objective_without_offers_still_forbids_them(db_tx) -> None:
    """The safe default has to keep working — this is the regression guard."""
    import mission as mission_mod

    card = _card_with_offers([])
    built = mission_mod.build(
        db_tx,
        customer_id="cust-susanth",
        objective="dpd_reminder",
        account_id="AC-SUSANTH",
        card=card,
        bot_id="kaia-v2-4",
    )
    assert built["allowedOffers"] == []
    assert "cross_sell" in built["prohibited"]
    assert "Do NOT mention any product" in mission_mod.briefing(built)


def test_hardship_still_suppresses_offers_whatever_the_card_says() -> None:
    """The card grants permission; it does not override the interlock.

    A borrower who has just declared hardship must not be pitched a top-up even
    on an objective that permits offers, and that stop lives in the tool rather
    than the prompt so no phrasing can route around it.
    """
    from tests.voice_tools_source import source

    src = source()
    assert 'session.extra["upsell_blocked"] = reason' in src, (
        "the hardship latch must still be set independently of the mission"
    )
    assert 'blocked = session.extra.get("upsell_blocked")' in src, (
        "the offer tool must still consult the latch"
    )
