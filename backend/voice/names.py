"""First-name matching for outbound identity confirm.

Kept free of ``db`` / ``persist`` so tests and the verify handler can import
it without opening a connection.
"""

from __future__ import annotations

import re

_NAME_WORD = re.compile(r"[A-Za-z]{3,}")


def _name_key(value: str) -> str:
    """Collapse common Indian-English transliteration noise (Sushant / Susanth)."""
    letters = "".join(ch for ch in (value or "").lower() if ch.isalpha())
    return letters.replace("sh", "s").replace("th", "t")


def first_names_match(spoken: str, expected: str) -> bool:
    """True when the caller said the expected first name (or a close variant).

    Outbound we already dialled the registered number; last-4 is a second
    factor, not the only one. ``Yeah, Sushant here`` must match ``Susanth``.
    """
    expected_first = (_NAME_WORD.findall(expected or "") or [""])[0]
    exp_key = _name_key(expected_first)
    if len(exp_key) < 3:
        return False
    for word in _NAME_WORD.findall(spoken or ""):
        got = _name_key(word)
        if got == exp_key:
            return True
        if len(got) >= 4 and (exp_key.startswith(got) or got.startswith(exp_key)):
            return True
    return False
