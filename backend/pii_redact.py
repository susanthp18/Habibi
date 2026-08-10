"""Free-text PII masking, shared by every path that persists customer words.

The detector set is the canonical one: it mirrors ``Habibi/src/data/redaction-seed.ts``
DETECTORS and the seed migrations (``20260722_0012`` / ``_0014``), which each carry
their own frozen copy because an applied migration must not import live code.

Existing redaction is *interaction*-scoped — ``redaction_records`` hangs off an
interaction and drives the review screen. Free text that lands outside that model
(``retrieval_logs.query``, which stores the caller's KB question verbatim) had no
masking at all, so a card number spoken into a "why was my card declined" query
was persisted in the clear and indefinitely.
"""

from __future__ import annotations

import re
from typing import Callable

__all__ = ["redact_text", "PII_DETECTORS"]


def _mask_card(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"**** **** **** {digits[-4:]}"


def _mask_aadhaar(s: str) -> str:
    return f"•••• •••• {s[-4:]}"


def _mask_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    return f"+91 ••••••••{digits[-2:]}"


def _mask_account(s: str) -> str:
    return f"••••{s[-4:]}"


# Order matters: card runs before aadhaar so a spaced 16-digit card is not
# partially consumed by the 12-digit aadhaar pattern (see migration _0014).
PII_DETECTORS: list[tuple[str, re.Pattern[str], Callable[[str], str]]] = [
    ("card", re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), _mask_card),
    ("aadhaar", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), _mask_aadhaar),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), lambda _s: "[REDACTED-PAN]"),
    ("phone", re.compile(r"\+91[- ]?\d{5}[- ]?\d{5}\b"), _mask_phone),
    (
        "email",
        re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I),
        lambda _s: "[REDACTED-EMAIL]",
    ),
    (
        "dob",
        re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[-/](?:0?[1-9]|1[0-2])[-/](?:19|20)\d{2}\b"),
        lambda _s: "[REDACTED-DOB]",
    ),
    ("account", re.compile(r"\bHDFC-(?:CC|PL|RL|AL)-\d{4}\b"), _mask_account),
]


def redact_text(text: str | None) -> str:
    """Return ``text`` with every detected PII span replaced by its mask."""
    out = text or ""
    if not out:
        return out
    for _kind, pattern, mask in PII_DETECTORS:
        out = pattern.sub(lambda m, _mask=mask: _mask(m.group(0)), out)
    return out
