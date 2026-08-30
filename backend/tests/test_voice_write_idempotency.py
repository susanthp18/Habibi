"""G3(a) — every voice CRM write must scope its idempotency key to the CALL.

The keys used to embed ``session.interaction_id``. A Twilio media-stream
reconnect makes ``start_voice_call`` mint a *new* interaction row, so the one
carrier event that most needs idempotency — a reconnect mid-conversation, where
the model re-does the write the caller already asked for — produced a second
row. For ``create_promise_to_pay`` that is money-relevant duplication; for the
three siblings it is a second dispute on one grievance, a second callback for
one slot, and the same statement generated and emailed twice. All four were
defeated by the very field the key was built on.

The fix keys on ``session.provider_call_id`` (Twilio CallSid / SmallWebRTC call
id), which survives the reconnect, and falls back to the interaction id for
local/sandbox sessions that have no provider id.

Every test here drives the production entry point — ``build_tools`` →
``tools[<name>].handler`` → ``agent_core.tools.domain`` → ``db.create_*`` — and
asserts on real rows, so the domain-layer dedupe lookup
(``db._idempotent_response``) is what is actually being exercised.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import pytest
from sqlalchemy import text

import db
from voice import tools as voice_tools
from voice.session import VoiceSession

PROMISE_DATE = "2026-09-14"


@pytest.fixture
def customer_id(db_tx) -> str:
    # UNKNOWN-CALLER is the unbound-caller sentinel; the write guard rejects it.
    cid = db_tx.execute(
        text("SELECT id FROM customers WHERE id <> :u ORDER BY id LIMIT 1"),
        {"u": "UNKNOWN-CALLER"},
    ).scalar()
    if not cid:
        pytest.skip("no customers seeded")
    return cid


def _interaction(db_tx, customer_id: str) -> str:
    """A fresh interaction row — one per 'connection', as a reconnect makes."""
    ix = f"IX-PTPIDEM-{uuid.uuid4().hex[:8].upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel,
               status, started_at)
            VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots LIMIT 1),
                    'voice', 'active', now() - interval '2 minutes')
            """
        ),
        {"id": ix, "t": db.TENANT_ID, "c": customer_id},
    )
    return ix


def _bot_id(db_tx) -> str | None:
    bot = getattr(db, "DEFAULT_BOT_ID", None)
    if not bot:
        return None
    ok = db_tx.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot}).fetchone()
    return bot if ok else None


def _keys_seen(monkeypatch: pytest.MonkeyPatch, fn_name: str = "create_promise_to_pay") -> list[str]:
    """Record the key without intercepting it — the real domain call still runs."""
    from agent_core.tools import domain

    seen: list[str] = []
    real = getattr(domain, fn_name)

    def _spy(**kwargs):
        seen.append(kwargs.get("idempotency_key"))
        return real(**kwargs)

    monkeypatch.setattr(domain, fn_name, _spy)
    return seen


def _call(
    db_tx,
    tool: str,
    args: dict[str, Any],
    *,
    customer_id: str,
    interaction_id: str,
    provider_call_id: str | None,
) -> dict:
    """One write driven through the production handler path."""
    session = VoiceSession(session_id=f"VS-{uuid.uuid4().hex[:8].upper()}")
    session.customer_id = customer_id
    session.identity_verified = True
    session.interaction_id = interaction_id
    session.provider_call_id = provider_call_id

    _state, tools = voice_tools.build_tools(
        session,
        bot_id=_bot_id(db_tx),
        start_recording=None,
        nodes={},
    )

    async def scenario():
        return await tools[tool].handler(args, None)

    result, _next = asyncio.run(scenario())
    return result


def _book(
    db_tx,
    *,
    customer_id: str,
    interaction_id: str,
    provider_call_id: str | None,
    amount: float,
) -> dict:
    """One PTP booked through the production handler path."""
    return _call(
        db_tx,
        "create_promise_to_pay",
        {"amount": amount, "promise_date": PROMISE_DATE},
        customer_id=customer_id,
        interaction_id=interaction_id,
        provider_call_id=provider_call_id,
    )


def _promise_count(db_tx, customer_id: str, amount: float) -> int:
    return db_tx.execute(
        text(
            "SELECT count(*) FROM promises "
            " WHERE customer_id = :c AND amount = :a AND promised_at = :d"
        ),
        {"c": customer_id, "a": amount, "d": PROMISE_DATE},
    ).scalar()


# ---------------------------------------------------------------------------
# The PTP regression, told in full (cycle 29).
# ---------------------------------------------------------------------------


def test_a_reconnect_mid_call_does_not_double_book_the_promise(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two interactions, one carrier call, one commitment → exactly one row.

    This is the regression: before the fix the second book minted a different
    key (the new interaction id) and inserted a second promise.
    """
    keys = _keys_seen(monkeypatch)
    amount = 411.0
    before = _promise_count(db_tx, customer_id, amount)
    call_sid = f"CA{uuid.uuid4().hex}"

    first = _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=_interaction(db_tx, customer_id),
        provider_call_id=call_sid,
        amount=amount,
    )
    # Reconnect: same carrier call, brand-new interaction row.
    second = _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=_interaction(db_tx, customer_id),
        provider_call_id=call_sid,
        amount=amount,
    )

    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    assert first["promiseId"] == second["promiseId"], "the reconnect booked a second promise"
    assert _promise_count(db_tx, customer_id, amount) == before + 1

    assert keys[0] == keys[1], keys
    assert keys[0] == f"voice-ptp:{call_sid}:{customer_id}:{amount:.2f}:{PROMISE_DATE}"


def test_two_genuinely_separate_calls_each_book_their_own_promise(
    db_tx, customer_id: str
) -> None:
    """Idempotency must not swallow a real second commitment on a later call."""
    amount = 412.0
    before = _promise_count(db_tx, customer_id, amount)

    first = _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=_interaction(db_tx, customer_id),
        provider_call_id=f"CA{uuid.uuid4().hex}",
        amount=amount,
    )
    second = _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=_interaction(db_tx, customer_id),
        provider_call_id=f"CA{uuid.uuid4().hex}",
        amount=amount,
    )

    assert first["promiseId"] != second["promiseId"]
    assert _promise_count(db_tx, customer_id, amount) == before + 2


def test_a_session_with_no_provider_id_still_keys_on_the_interaction(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local/sandbox shape: behaviour is exactly what it was before the fix."""
    keys = _keys_seen(monkeypatch)
    amount = 413.0
    before = _promise_count(db_tx, customer_id, amount)
    ix = _interaction(db_tx, customer_id)

    first = _book(
        db_tx, customer_id=customer_id, interaction_id=ix, provider_call_id=None, amount=amount
    )
    # Same interaction, double tool-call — still deduped.
    second = _book(
        db_tx, customer_id=customer_id, interaction_id=ix, provider_call_id=None, amount=amount
    )
    # Different interaction, no provider id — nothing ties them together, so
    # this inserts, exactly as it did under the old key.
    third = _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=_interaction(db_tx, customer_id),
        provider_call_id=None,
        amount=amount,
    )

    assert first["promiseId"] == second["promiseId"]
    assert third["promiseId"] != first["promiseId"]
    assert _promise_count(db_tx, customer_id, amount) == before + 2
    assert keys[0] == f"voice-ptp:{ix}:{customer_id}:{amount:.2f}:{PROMISE_DATE}"


def test_the_provider_id_wins_over_the_interaction_id(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guards the precedence itself, not just its effect on row counts."""
    keys = _keys_seen(monkeypatch)
    amount = 414.0
    call_sid = f"CA{uuid.uuid4().hex}"
    ix = _interaction(db_tx, customer_id)

    _book(
        db_tx,
        customer_id=customer_id,
        interaction_id=ix,
        provider_call_id=call_sid,
        amount=amount,
    )

    assert call_sid in keys[0]
    assert ix not in keys[0], "the interaction id is still scoping the key"


# ---------------------------------------------------------------------------
# The same three properties, for all four voice write tools (cycle 30).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteTool:
    """One voice write tool, described well enough to drive it generically."""

    tool: str
    domain_fn: str
    prefix: str
    id_field: str
    # A per-scenario discriminator, unique enough that row counts for one test
    # never see another test's rows.
    marker: Callable[[], Any]
    args: Callable[[Any], dict[str, Any]]
    # The part of the key after the call scope — must be untouched by the fix.
    suffix: Callable[[str, Any], str]
    count: Callable[[Any, str, Any], int]


def _unique_amount() -> float:
    """A two-decimal amount inside every seeded account's outstanding."""
    return 100.0 + (int(uuid.uuid4().hex[:6], 16) % 30000) / 100.0


def _count_where(db_tx, table: str, column: str, customer_id: str, value: Any) -> int:
    return db_tx.execute(
        text(  # noqa: S608 - table/column are literals from WRITE_TOOLS
            f"SELECT count(*) FROM {table} WHERE customer_id = :c AND {column} = :v"
        ),
        {"c": customer_id, "v": value},
    ).scalar()


def _count_amount(db_tx, table: str, column: str, customer_id: str, amount: float) -> int:
    """Amount columns are numeric(14,2); the marker is a float.

    Comparing the raw float loses: 334.42 arrives as 334.41999999999996 and
    matches nothing. Round-trip through the same two-decimal text the key uses.
    """
    return db_tx.execute(
        text(  # noqa: S608 - table/column are literals from WRITE_TOOLS
            f"SELECT count(*) FROM {table} "
            f" WHERE customer_id = :c AND {column} = cast(:v AS numeric)"
        ),
        {"c": customer_id, "v": f"{amount:.2f}"},
    ).scalar()


WRITE_TOOLS = (
    WriteTool(
        tool="create_promise_to_pay",
        domain_fn="create_promise_to_pay",
        prefix="voice-ptp",
        id_field="promiseId",
        marker=_unique_amount,
        args=lambda amt: {"amount": amt, "promise_date": PROMISE_DATE},
        suffix=lambda cid, amt: f"{cid}:{amt:.2f}:{PROMISE_DATE}",
        count=lambda db_tx, cid, amt: db_tx.execute(
            text(
                "SELECT count(*) FROM promises WHERE customer_id = :c"
                "   AND amount = cast(:a AS numeric) AND promised_at = :d"
            ),
            {"c": cid, "a": f"{amt:.2f}", "d": PROMISE_DATE},
        ).scalar(),
    ),
    WriteTool(
        tool="flag_dispute",
        domain_fn="flag_dispute",
        prefix="voice-dispute",
        id_field="disputeId",
        marker=_unique_amount,
        args=lambda amt: {"dispute_type": "paid_already", "amount": amt},
        suffix=lambda cid, amt: f"{cid}:paid_already:{amt:.2f}",
        count=lambda db_tx, cid, amt: _count_amount(
            db_tx, "disputes", "disputed_amount", cid, amt
        ),
    ),
    WriteTool(
        tool="request_callback",
        domain_fn="request_callback",
        prefix="voice-callback",
        id_field="callbackId",
        # Distinct wall-clock second per scenario: the callback key carries the
        # raw scheduled_at string, and the row is found by the stored instant.
        marker=lambda: "2026-09-1"
        + str(int(uuid.uuid4().hex[:2], 16) % 9)
        + f"T1{int(uuid.uuid4().hex[:2], 16) % 10}:"
        + f"{int(uuid.uuid4().hex[2:4], 16) % 60:02d}:"
        + f"{int(uuid.uuid4().hex[4:6], 16) % 60:02d}+05:30",
        args=lambda when: {"scheduled_at": when, "reason": "general", "window_mins": 30},
        suffix=lambda cid, when: f"{cid}:{when}",
        count=lambda db_tx, cid, when: _count_where(
            db_tx, "callbacks", "scheduled_at", cid, when
        ),
    ),
    WriteTool(
        tool="request_documents",
        domain_fn="request_documents",
        prefix="voice-doc",
        id_field="documentRequestId",
        marker=lambda: f"P-{uuid.uuid4().hex[:10].upper()}",
        args=lambda period: {"document_type": "account_statement", "period": period},
        suffix=lambda cid, period: f"{cid}:account_statement:{period}",
        count=lambda db_tx, cid, period: _count_where(
            db_tx, "document_requests", "period", cid, period
        ),
    ),
)

_IDS = [w.tool for w in WRITE_TOOLS]


def _drive(db_tx, spec: WriteTool, marker: Any, *, customer_id: str, ix: str, call_id: str | None):
    return _call(
        db_tx,
        spec.tool,
        spec.args(marker),
        customer_id=customer_id,
        interaction_id=ix,
        provider_call_id=call_id,
    )


@pytest.mark.parametrize("spec", WRITE_TOOLS, ids=_IDS)
def test_reconnect_under_one_carrier_call_writes_one_row(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch, spec: WriteTool
) -> None:
    """Same provider_call_id, two interaction ids → deduped to a single row."""
    keys = _keys_seen(monkeypatch, spec.domain_fn)
    marker = spec.marker()
    before = spec.count(db_tx, customer_id, marker)
    call_sid = f"CA{uuid.uuid4().hex}"

    first = _drive(
        db_tx,
        spec,
        marker,
        customer_id=customer_id,
        ix=_interaction(db_tx, customer_id),
        call_id=call_sid,
    )
    # Reconnect: same carrier call, brand-new interaction row.
    second = _drive(
        db_tx,
        spec,
        marker,
        customer_id=customer_id,
        ix=_interaction(db_tx, customer_id),
        call_id=call_sid,
    )

    assert first.get("ok") is True, first
    assert second.get("ok") is True, second
    assert first[spec.id_field] == second[spec.id_field], "the reconnect wrote a second row"
    assert spec.count(db_tx, customer_id, marker) == before + 1

    assert keys[0] == keys[1], keys
    assert keys[0] == f"{spec.prefix}:{call_sid}:{spec.suffix(customer_id, marker)}"


@pytest.mark.parametrize("spec", WRITE_TOOLS, ids=_IDS)
def test_two_separate_carrier_calls_each_write_their_own_row(
    db_tx, customer_id: str, spec: WriteTool
) -> None:
    """Different provider_call_ids → both insert; dedupe must not over-reach."""
    marker = spec.marker()
    before = spec.count(db_tx, customer_id, marker)

    first = _drive(
        db_tx,
        spec,
        marker,
        customer_id=customer_id,
        ix=_interaction(db_tx, customer_id),
        call_id=f"CA{uuid.uuid4().hex}",
    )
    second = _drive(
        db_tx,
        spec,
        marker,
        customer_id=customer_id,
        ix=_interaction(db_tx, customer_id),
        call_id=f"CA{uuid.uuid4().hex}",
    )

    assert first[spec.id_field] != second[spec.id_field]
    assert spec.count(db_tx, customer_id, marker) == before + 2


@pytest.mark.parametrize("spec", WRITE_TOOLS, ids=_IDS)
def test_no_provider_id_falls_back_to_the_interaction_id(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch, spec: WriteTool
) -> None:
    """Local/sandbox shape: behaviour is exactly what it was before the fix."""
    keys = _keys_seen(monkeypatch, spec.domain_fn)
    marker = spec.marker()
    before = spec.count(db_tx, customer_id, marker)
    ix = _interaction(db_tx, customer_id)

    first = _drive(db_tx, spec, marker, customer_id=customer_id, ix=ix, call_id=None)
    # Same interaction, double tool-call — still deduped.
    second = _drive(db_tx, spec, marker, customer_id=customer_id, ix=ix, call_id=None)
    # Different interaction, no provider id — nothing ties them together, so
    # this inserts, exactly as it did under the old key.
    third = _drive(
        db_tx,
        spec,
        marker,
        customer_id=customer_id,
        ix=_interaction(db_tx, customer_id),
        call_id=None,
    )

    assert first[spec.id_field] == second[spec.id_field]
    assert third[spec.id_field] != first[spec.id_field]
    assert spec.count(db_tx, customer_id, marker) == before + 2
    assert keys[0] == f"{spec.prefix}:{ix}:{spec.suffix(customer_id, marker)}"


@pytest.mark.parametrize("spec", WRITE_TOOLS, ids=_IDS)
def test_the_provider_id_wins_over_the_interaction_id_everywhere(
    db_tx, customer_id: str, monkeypatch: pytest.MonkeyPatch, spec: WriteTool
) -> None:
    """Guards the precedence itself, not just its effect on row counts."""
    keys = _keys_seen(monkeypatch, spec.domain_fn)
    marker = spec.marker()
    call_sid = f"CA{uuid.uuid4().hex}"
    ix = _interaction(db_tx, customer_id)

    _drive(db_tx, spec, marker, customer_id=customer_id, ix=ix, call_id=call_sid)

    assert call_sid in keys[0]
    assert ix not in keys[0], "the interaction id is still scoping the key"
