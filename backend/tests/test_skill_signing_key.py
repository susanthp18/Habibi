"""An unconfigured deployment must not verify skill signatures against a constant.

``verify_signature`` is the G9 publish gate: a pack may attach to a published
card only if its content hash carries a valid platform signature. The key
behind that HMAC fell back to ``"dev-skill-platform-key-not-for-prod"`` — a
literal in this repository — whenever ``SKILL_PLATFORM_KEY`` was unset.

A production deploy that simply forgot the variable therefore accepted any
signature an attacker could compute from public source, which is the same as
having no gate. The fallback is still right for a laptop, so the fix is not to
remove it but to require the environment to *say* it is not production.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither variable may leak in from the developer's shell or .env."""
    monkeypatch.delenv("SKILL_PLATFORM_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


def _expected(key: str, content_hash: str) -> str:
    return hmac.new(key.encode("utf-8"), content_hash.encode("utf-8"), hashlib.sha256).hexdigest()


# --- missing key, production ------------------------------------------------


# --- missing key, development -----------------------------------------------


# --- key configured ---------------------------------------------------------


def test_the_template_does_not_ship_the_development_key() -> None:
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    for line in example.read_text(encoding="utf-8").splitlines():
        if line.startswith("SKILL_PLATFORM_KEY="):
            assert line == "SKILL_PLATFORM_KEY="
