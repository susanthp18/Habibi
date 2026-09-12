"""Small numeric helpers with one owner."""

from __future__ import annotations


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """``value`` held to ``[lo, hi]``. Four modules carried a private copy."""
    return max(lo, min(hi, value))
