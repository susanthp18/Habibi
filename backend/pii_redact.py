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

__all__ = ["redact_text", "PII_DETECTORS", "audit_args", "audit_preview", "ARGS_WITHHELD"]


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


# --- tool-call audit rows ----------------------------------------------------
#
# These lived in voice/persist.py and were applied only on the voice path, so
# WhatsApp, MCP and the sandbox wrote tool arguments and results verbatim. The
# sharpest case: `identify_customer` is a TEXT-channel-only spec taking `phone`
# and `account_tail` -- precisely the shape voice withholds -- landing in a
# column the Inbox renders. Moved here, and applied inside
# `bot_jobs.record_tool_call`, so the redaction is a property of writing the row
# rather than of remembering to call it.

#: Tools whose arguments are never stored. Both exist to receive digits the
#: caller spoke -- a mobile tail, an account tail -- and an audit row is not a
#: place to keep them. The *fact* that verification ran is the auditable thing;
#: the digits are what the verification was protecting.
ARGS_WITHHELD: frozenset[str] = frozenset({"verify_identity", "identify_customer"})

#: Argument names that carry free-form caller speech. Kept, but through the same
#: redactor the transcript uses, so a spoken card number in a dispute summary
#: does not survive in a column nobody thinks of as a transcript.
ARGS_REDACTED: frozenset[str] = frozenset(
    {"summary", "text", "note", "reason", "verbatim", "context", "question", "detail"}
)

#: Arguments never exceed this once serialised. A model that emits a wall of
#: text into a tool argument should not be able to grow this table without
#: bound, and nothing downstream reads past the useful fields.
MAX_ARGS_CHARS = 4000

#: Result previews are longer than arguments and are stored whole, so they get
#: the same ceiling and the same redactor.
MAX_PREVIEW_CHARS = 1500


def audit_args(tool_name: str, args: "dict[str, object] | None") -> dict:
    """What of a tool's arguments is safe to keep on the audit row."""
    import json

    if not isinstance(args, dict) or not args:
        return {}
    if tool_name in ARGS_WITHHELD:
        return {"_withheld": True}
    out: dict = {}
    for key, value in args.items():
        if isinstance(value, str):
            cleaned = redact_text(value) if key in ARGS_REDACTED else value
            out[key] = cleaned[:1000]
        elif isinstance(value, (int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = str(value)[:500]
    if len(json.dumps(out, default=str)) > MAX_ARGS_CHARS:
        return {"_truncated": True}
    return out


def audit_preview(preview: str | None) -> str | None:
    """A tool's result, masked and bounded, for `bot_tool_calls.result_preview`.

    bot_runtime set this to ``json.dumps(payload)[:1500]`` verbatim. A result is
    where a balance, a phone number or an address actually comes *back* from the
    CRM, so it leaked more than the arguments did.
    """
    if preview is None:
        return None
    return redact_text(str(preview))[:MAX_PREVIEW_CHARS]
