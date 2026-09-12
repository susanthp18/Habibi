"""Identity is an assurance level, and a blocked gate says how to pass it.

Before this, `identity_verifications` had never received a row from the text
channel — every row in the live table came from a voice call — so on WhatsApp
every gated tool was refused forever. In the thread that prompted this work,
three refusals landed in a row:

    recommend_next_offer       human_gate_identity
    capture_nonpayment_reason  human_gate_identity
    add_customer_note          human_gate_identity

and the model responded by offering a callback, which is also gated. It was
never told what would have worked.

The cause was one line in `capture_identity.rebind_interaction_customer`: an
`account_tail` match was downgraded to `status='pending'`, while the gate
required `'verified'`. So the only ceremony a customer can perform in a chat
thread wrote a row that could never open the gate, and `phone_match` — the other
option — asks a customer to type back the number the bot is messaging them on.
"""

from __future__ import annotations

import pytest

from agent_core.tools import gates


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_levels_are_ordered() -> None:
    assert gates.meets(gates.LEVEL_CHALLENGE, gates.LEVEL_ENDPOINT)
    assert gates.meets(gates.LEVEL_ENDPOINT, gates.LEVEL_ENDPOINT)
    assert not gates.meets(gates.LEVEL_ENDPOINT, gates.LEVEL_CHALLENGE)
    assert not gates.meets(gates.LEVEL_NONE, gates.LEVEL_ENDPOINT)


def test_a_proven_endpoint_opens_the_reversible_writes() -> None:
    """A note or a callback costs an apology if it is wrong."""
    for tool in ("add_customer_note", "request_callback", "recommend_next_offer",
                 "set_contact_preference", "capture_nonpayment_reason"):
        assert gates.gate_failure(
            tool, card={}, assurance=gates.LEVEL_ENDPOINT
        ) is None, f"{tool} should not need a challenge"


def test_money_and_regulated_acts_still_need_a_challenge() -> None:
    """These cost the customer something they cannot undo."""
    for tool in ("create_promise_to_pay", "flag_dispute", "apply_goodwill",
                 "handoff_to_agent", "request_documents"):
        blocked = gates.gate_failure(tool, card={}, assurance=gates.LEVEL_ENDPOINT)
        assert blocked is not None, f"{tool} must not open on a phone match alone"
        assert blocked["required"] == gates.LEVEL_CHALLENGE
        assert gates.gate_failure(
            tool, card={}, assurance=gates.LEVEL_CHALLENGE
        ) is None


def test_reaching_a_person_never_requires_passing_a_ceremony() -> None:
    """Unchanged, and for the reason already recorded in the module."""
    assert gates.gate_failure(
        "escalate_to_human", card={}, assurance=gates.LEVEL_NONE
    ) is None


# ---------------------------------------------------------------------------
# A refusal that cannot be acted on is not a refusal, it is a dead end
# ---------------------------------------------------------------------------


def test_a_blocked_tool_says_what_would_unblock_it() -> None:
    blocked = gates.gate_failure(
        "create_promise_to_pay", card={}, assurance=gates.LEVEL_ENDPOINT
    )
    assert blocked["error"] == gates.GATE_IDENTITY
    assert blocked["have"] == gates.LEVEL_ENDPOINT
    assert "identify_customer" in blocked["hint"]
    assert "last 4" in blocked["hint"]


def test_the_hint_reaches_the_model(monkeypatch) -> None:
    """The dispatcher must pass the remedy through, not just the code."""
    import inspect

    import bot_tools

    src = inspect.getsource(bot_tools.execute_tool)
    assert "interaction_assurance(" in src
    assert '{"ok": False, **blocked}' in src


# ---------------------------------------------------------------------------
# Methods map to levels, and the two channels agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,level",
    [
        ("phone_match", gates.LEVEL_ENDPOINT),
        ("account_tail", gates.LEVEL_CHALLENGE),
        ("dob", gates.LEVEL_CHALLENGE),
        ("otp", gates.LEVEL_CHALLENGE),
        ("manual", gates.LEVEL_CHALLENGE),
    ],
)
def test_each_method_earns_its_level(method: str, level: str) -> None:
    assert gates._METHOD_LEVEL[method] == level


def _live_code(fn) -> str:
    """Source with comments stripped.

    This codebase records removed code in comments — deliberately, and it is
    worth keeping — so a source-inspection test that greps the raw text matches
    the epitaph as well as the corpse.
    """
    import inspect

    return "\n".join(
        line for line in inspect.getsource(fn).splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_text_channel_no_longer_downgrades_a_tail_to_pending() -> None:
    """The one line that made the WhatsApp ceremony unpassable.

    `_tool_identify_customer` already requires the matched customer's phone to
    equal the thread's phone, so an account_tail match there is two factors, not
    one. Recording two factors as "pending" was not caution.
    """
    import capture_identity

    assert 'verification_status = "pending"' not in _live_code(
        capture_identity.rebind_interaction_customer
    )


def test_voice_and_text_agree_about_what_a_method_means() -> None:
    """They did not: voice wrote account_tail as verified, text as pending."""
    import capture_identity
    import voice.persist as vp

    for fn in (capture_identity.rebind_interaction_customer, vp.record_identity_verification):
        assert 'if method == "account_tail"' not in _live_code(fn)


# ---------------------------------------------------------------------------
# The old boolean API still means the strong thing
# ---------------------------------------------------------------------------


def test_the_compat_shim_does_not_quietly_weaken_a_gate() -> None:
    """A caller still speaking in booleans has not been taught about levels.

    Reading its True as merely `endpoint` would silently open money tools to a
    phone match, which is the opposite of what that caller thinks it is saying.
    """
    assert gates.enforce_human_gate(
        "create_promise_to_pay", card={}, identity_verified=True
    ) is None
    assert gates.enforce_human_gate(
        "create_promise_to_pay", card={}, identity_verified=False
    ) == gates.GATE_IDENTITY
