"""Load backend/.env into os.environ (non-destructive: existing env wins)."""

from __future__ import annotations

import os
from pathlib import Path

_ENV_FILE = Path(__file__).resolve().parent / ".env"
_LOADED = False


def load_env(force: bool = False) -> None:
    global _LOADED
    if _LOADED and not force:
        return
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _LOADED = True


def env_str(name: str, default: str = "") -> str:
    """A settings string, with ``.env`` loaded first. Blank counts as unset.

    Five modules — ``payments``, ``payment_events``, ``promise_fulfillment``,
    ``twilio_sms`` and ``voice.twilio_ops`` — each defined this as a private
    ``_env``, byte for byte the same three lines. It lives here rather than in
    ``env_utils`` because the ``load_env()`` call is the whole point of it, and
    ``env_utils`` is deliberately a leaf that imports nothing but ``math`` and
    ``os`` so the signing key and the vault key can both take it.
    """
    load_env()
    return (os.getenv(name) or default).strip()
