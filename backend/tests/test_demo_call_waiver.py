"""What a test call may waive, and what it may never waive.

A test call (Settings > Test call, ``voice_studio_testcall``) rings only a
handset on the tenant's test-number list, never a number typed into the
request, so it cannot be pointed at a borrower. Rehearsing hits `cooling_off`
after a few calls, which is the frequency rule working correctly on the wrong
subject. Those frequency refusals are always overridden. Calling hours and the
borrower's preferred window stay behind the operator switch, so a rehearsal
can still show the statutory gate.

Nothing here waives *whether*: a person who opted out, registered DND, or
never gave a promotional basis is not callable for a test either, and no
switch setting changes that.

This file exists because that line is the whole safety argument for having the
waiver at all, and a line nobody tests is a line that moves.
"""

from __future__ import annotations

import inspect

import pytest

import contact_policy
import platform_switches
import voice_studio_testcall as testcall

_TIMING = frozenset({
    contact_policy.REASON_HOURS,
    contact_policy.REASON_WINDOW,
    contact_policy.REASON_COOLING,
    contact_policy.REASON_DAILY,
    contact_policy.REASON_WEEKLY,
})
_FREQUENCY = frozenset({contact_policy.REASON_COOLING, contact_policy.REASON_DAILY, contact_policy.REASON_WEEKLY})


@pytest.fixture(params=[False, True], ids=["hours-enforced", "hours-waived"])
def switch(request, monkeypatch: pytest.MonkeyPatch) -> bool:
    monkeypatch.setattr(platform_switches, "demo_ignores_window", lambda **_kw: request.param)
    return request.param


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
def test_consent_refusals_are_never_waivable(reason: str, switch: bool) -> None:
    """A rehearsal does not get to re-answer "did this person agree to be called"."""
    assert reason not in testcall.waivers()


def test_frequency_is_waived_even_when_the_hours_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_switches, "demo_ignores_window", lambda **_kw: False)
    assert testcall.waivers() == _FREQUENCY


def test_the_hours_switch_adds_only_the_clock_vetoes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned as a set, so a sixth reason cannot be added without deciding to."""
    monkeypatch.setattr(platform_switches, "demo_ignores_window", lambda **_kw: True)
    assert testcall.waivers() == _TIMING
    assert platform_switches.DEMO_IGNORES_WINDOW in platform_switches.KNOWN_KEYS


def test_every_waiver_is_written_to_the_audit_trail() -> None:
    """Overriding a compliance veto is exactly the event an auditor asks about."""
    src = inspect.getsource(testcall.place)
    assert "waivable=waived" in src
    assert "record_activity" in src
    assert "demo_window_waived" in src
    assert 'f"waived:{reason}"' in src


def test_the_call_takes_no_phone_number() -> None:
    """The containment argument depends on this: the number is a test-number id."""
    params = list(inspect.signature(testcall.place).parameters)
    assert params == ["agent_id", "number_id", "objective", "actor"]
    assert "FROM test_numbers WHERE id = :id AND tenant_id = :t" in inspect.getsource(testcall._number)
