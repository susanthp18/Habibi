"""HMAC-SHA256 signatures over a skill content hash.

The platform key signs first-party packs. Tenant keys are Phase 5.
Unsigned packs are drafts: they cannot attach to a published card (G9).
The gardener must not call ``sign_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import os


def platform_key() -> bytes:
    raw = (os.getenv("SKILL_PLATFORM_KEY") or "dev-skill-platform-key-not-for-prod").encode("utf-8")
    return raw


def sign_hash(content_hash: str, *, key: bytes | None = None) -> str:
    material = (content_hash or "").encode("utf-8")
    return hmac.new(key or platform_key(), material, hashlib.sha256).hexdigest()


def verify_signature(content_hash: str, signature: str | None, *, key: bytes | None = None) -> bool:
    if not signature:
        return False
    expected = sign_hash(content_hash, key=key)
    return hmac.compare_digest(expected, signature)
