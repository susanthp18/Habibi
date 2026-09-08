"""Refuse a real carrier when a test or a disabled adapter would reach one.

Enactment integration tests must fail closed if they forget to stub Twilio or
Meta. The live adapters call :func:`refuse_real_carrier` on the way out; a
pytest run without an explicit override raises rather than placing a call.
"""

from __future__ import annotations

import os

from env_utils import env_bool

_OVERRIDE = "HABIBI_ALLOW_LIVE_CARRIER_IN_TEST"


class RealCarrierRefused(RuntimeError):
    """A test reached a live voice, SMS, or WhatsApp adapter."""


def under_test() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def refuse_real_carrier(surface: str) -> None:
    """Raise when pytest would otherwise talk to a provider.

    Production and local non-test processes pass through. Tests that intend to
    exercise a fake must patch the adapter *before* this line; tests that
    forget get a failure instead of a live dial.
    """
    if not under_test():
        return
    if env_bool(_OVERRIDE):
        return
    raise RealCarrierRefused(
        f"{surface} must not run under pytest; stub the adapter or the test "
        "is about to contact a real borrower"
    )
