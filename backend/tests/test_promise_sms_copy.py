"""The written confirmation and the due-day reminder fit an SMS.

Run 88's confirmation carried the rupee sign, which makes the whole message
UCS-2 (67 characters a segment): four segments, refused by the carrier
(Twilio 30044). It also said "Rs 5,000 by 06 Oct" for a promise paid in parts.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import promise_fulfillment as pf

# GSM 03.38 basic set (the extension table's characters count double and are not needed).
_GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
# The production pay link's length: https://beeonixpayint.bigtapp.net/pay/<32-char token>.
_PAY_URL = "https://beeonixpayint.bigtapp.net/pay/" + "x" * 32


def _segments(body: str) -> int:
    assert set(body) <= _GSM7, set(body) - _GSM7
    return 1 if len(body) <= 160 else math.ceil(len(body) / 153)


def test_the_confirmation_lists_the_parts_in_gsm7_within_two_segments() -> None:
    body = pf._confirm_copy(
        amount=5000, promised_at=datetime(2026, 10, 6, 18, 30, tzinfo=timezone.utc), pay_url=_PAY_URL,
        expires_at=datetime(2026, 10, 8, 18, 29, 59, tzinfo=timezone.utc),
        parts=[{"amount": 2500, "date": "2026-10-02"}, {"amount": 2500, "date": "2026-10-07"}],
    )
    assert "VND 5.000 by 07 Oct (VND 2.500 by 02 Oct, VND 2.500 by 07 Oct)" in body
    assert _PAY_URL in body and "valid till 08 Oct" in body
    assert _segments(body) <= 2, len(body)


def test_one_payment_and_a_due_reminder_also_fit() -> None:
    one = pf._confirm_copy(amount=480000, promised_at=datetime(2026, 10, 6, 18, 30, tzinfo=timezone.utc),
                           pay_url=_PAY_URL, expires_at=None)
    assert "VND 480.000 by 07 Oct" in one and _segments(one) <= 2
    due = pf._due_copy(amount=2500, pay_url=_PAY_URL, part=(1, 2))
    assert "VND 2.500 is due today" in due and "part 1 of 2" in due
    assert _segments(due) <= 2
