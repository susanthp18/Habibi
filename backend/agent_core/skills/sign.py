"""HMAC-SHA256 signatures over a skill content hash.

The platform key signs first-party packs. Tenant keys are Phase 5.
Unsigned packs are drafts: they cannot attach to a published card (G9).
The gardener must not call ``sign_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import os

# ``env_utils`` is the leaf: the vault master key asks the same "is this
# actually a laptop?" question, and it must not have to import the skill
# signer to do it.
from env_utils import NON_PROD_ENVS, env_name

DEV_PLATFORM_KEY = "dev-skill-platform-key-not-for-prod"


def platform_key() -> bytes:
    """The HMAC key behind the G9 publish gate.

    ``verify_signature`` is what decides a pack may attach to a published card.
    Falling back to ``DEV_PLATFORM_KEY`` whenever ``SKILL_PLATFORM_KEY`` was
    unset meant an unconfigured production deploy verified against a public
    constant — anyone reading this file could forge a signature and get a pack
    past the gate. Outside a declared non-production environment a missing key
    is now an error at verify/sign time rather than a silently weaker check.
    """
    raw = (os.getenv("SKILL_PLATFORM_KEY") or "").strip()
    if raw:
        return raw.encode("utf-8")
    env = env_name()
    if env not in NON_PROD_ENVS:
        raise RuntimeError(
            "SKILL_PLATFORM_KEY is not set and APP_ENV=" + env + " is not a "
            "non-production environment " + str(sorted(NON_PROD_ENVS)) + ". "
            "Skill signatures cannot be verified against the built-in "
            "development key outside development. Set SKILL_PLATFORM_KEY."
        )
    return DEV_PLATFORM_KEY.encode("utf-8")


def sign_hash(content_hash: str, *, key: bytes | None = None) -> str:
    material = (content_hash or "").encode("utf-8")
    return hmac.new(key or platform_key(), material, hashlib.sha256).hexdigest()


def verify_signature(content_hash: str, signature: str | None, *, key: bytes | None = None) -> bool:
    if not signature:
        return False
    expected = sign_hash(content_hash, key=key)
    return hmac.compare_digest(expected, signature)
