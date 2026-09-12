"""The PII encryption key, and the one way it reaches Postgres.

``customers.phone_primary``, ``phone_alt``, ``email`` and ``address`` are
stored encrypted (``sql/01_pii.sql``); the ``customers`` relation the
application uses is a view that decrypts with the ``app.pii_key`` GUC. The key
travels as a libpq startup parameter -- the same mechanism as the tenant --
so there is no window in which a pooled connection could read without it, and
it is never interpolated into SQL text.

On-prem, the value comes from the deployment's secret store into
``PII_ENCRYPTION_KEY`` (docs/ops/vault-inventory.md). There is deliberately no
default: a process without a key reads NULL through the view and cannot
write a customer row (``pii_encrypt`` refuses), and the hardening gate lists
the control as inactive.

Rotation: ``scripts/rotate_pii_key.py`` re-encrypts under a new key; not
automated, by design.

``env_utils``-style leaf: imports nothing but the stdlib and ``env_loader``.
"""

from __future__ import annotations

import re

from env_loader import env_str

#: The GUC the view's functions read.
GUC = "app.pii_key"

#: A startup option cannot carry whitespace or a backslash, and a key an
#: operator pastes should not need quoting anywhere. Base64url or hex.
_SAFE = re.compile(r"^[A-Za-z0-9_\-]{32,256}$")


def key() -> str | None:
    """The configured key, or None. An unsafe value is a configuration error."""
    raw = env_str("PII_ENCRYPTION_KEY")
    if not raw:
        return None
    if not _SAFE.fullmatch(raw):
        raise RuntimeError(
            "PII_ENCRYPTION_KEY must be 32-256 characters of [A-Za-z0-9_-]; "
            "it is passed as a connection startup parameter"
        )
    return raw


def configured() -> bool:
    return key() is not None


def connect_option() -> str:
    """The ``-c app.pii_key=...`` fragment for libpq ``options``, or ``""``."""
    k = key()
    return f"-c {GUC}={k}" if k else ""
