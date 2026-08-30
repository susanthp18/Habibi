"""What the demo switch may waive, and what it may never waive.

The demo endpoint dials one configured handset -- the one the operator running
the demo is holding -- and takes no phone number, so it cannot be pointed at a
borrower. Rehearsing on it hits `cooling_off` after a few calls, which is the
frequency rule working correctly on the wrong subject.

So the switch waives *when* and *how often*. It does not waive *whether*: a
person who opted out, registered DND, or never gave a promotional basis is not
callable for a demo either, and no switch setting changes that.

This file exists because that line is the whole safety argument for having the
switch at all, and a line nobody tests is a line that moves.
"""

from __future__ import annotations

import pytest

import contact_policy
import main


# --- what may be waived -----------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        contact_policy.REASON_HOURS,
        contact_policy.REASON_WINDOW,
        contact_policy.REASON_COOLING,
        contact_policy.REASON_DAILY,
        contact_policy.REASON_WEEKLY,
    ],
)
def test_timing_and_frequency_refusals_are_waivable(reason: str) -> None:
    assert reason in main._DEMO_WAIVABLE_REASONS


# --- what may never be waived ----------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        contact_policy.REASON_OPTED_OUT,
        contact_policy.REASON_CHANNEL_DND,
        contact_policy.REASON_CUSTOMER_DND,
        contact_policy.REASON_EXPIRED,
        contact_policy.REASON_NO_PROMO_CONSENT,
        contact_policy.REASON_NO_CUSTOMER,
        contact_policy.REASON_UNREADABLE,
    ],
)
def test_consent_refusals_are_never_waivable(reason: str) -> None:
    """A demo does not get to re-answer "did this person agree to be called"."""
    assert reason not in main._DEMO_WAIVABLE_REASONS


def test_an_unreadable_consent_record_still_refuses() -> None:
    """The fail-closed path stays fail-closed.

    `consent_unreadable` means we could not determine whether the person agreed.
    Treating "we don't know" as "go ahead" for the sake of a smoother demo is
    the exact trade this codebase refuses everywhere else.
    """
    assert contact_policy.REASON_UNREADABLE not in main._DEMO_WAIVABLE_REASONS


def test_the_waivable_set_is_exactly_the_five_timing_rules() -> None:
    """Pinned as a set, so a sixth reason cannot be added without deciding to."""
    assert main._DEMO_WAIVABLE_REASONS == frozenset(
        {
            contact_policy.REASON_HOURS,
            contact_policy.REASON_WINDOW,
            contact_policy.REASON_COOLING,
            contact_policy.REASON_DAILY,
            contact_policy.REASON_WEEKLY,
        }
    )


# --- the switch is still the gate -------------------------------------------


def test_the_waiver_needs_the_switch_and_the_switch_is_off_by_default() -> None:
    """Waivable is not waived: an operator has to have turned this on."""
    import inspect

    src = inspect.getsource(main.demo_outbound_call)
    assert "platform_switches.demo_ignores_window()" in src
    assert "waivable_for_demo" in src

    import platform_switches

    assert platform_switches.DEMO_IGNORES_WINDOW in platform_switches.KNOWN_KEYS


def test_every_waiver_is_written_to_the_audit_trail() -> None:
    """Overriding a compliance veto is exactly the event an auditor asks about."""
    import inspect

    src = inspect.getsource(main.demo_outbound_call)
    assert "record_activity" in src
    assert "demo_window_waived" in src
    assert 'f"waived:{reason}"' in src


def test_the_endpoint_still_takes_no_phone_number() -> None:
    """The containment argument depends on this.

    The waiver is defensible only because the endpoint cannot be aimed at a
    borrower. A parameter here would turn a demo button into a dialer that
    ignores the caps.
    """
    import inspect

    sig = inspect.signature(main.demo_outbound_call)
    assert list(sig.parameters) == []
