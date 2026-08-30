"""Authenticated local envelope for vault_refs.ciphertext.

Not Azure Key Vault. When AZURE_KEY_VAULT_URL is set the Azure backend is
used and ciphertext stays null. This is HMAC-SHA256 CTR + HMAC tag so the
API image does not grow a crypto extra for tests.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

# The "is this actually a laptop?" test, shared rather than re-typed: a second
# copy of an allow-list like this drifts, and the two keys it guards must agree
# on what counts as production. It lives in ``env_utils`` — the leaf — rather
# than in the skill signer, so sealing a connector credential does not drag in
# skill packs to answer a question about ``APP_ENV``.
from env_utils import NON_PROD_ENVS, env_name

_NONCE = 16
_TAG = 32

DEV_MASTER_KEY = "dev-vault-master-key-not-for-prod"


def master_key() -> bytes:
    """The key every ``vault_refs.ciphertext`` is sealed under.

    ``VAULT_MASTER_KEY`` is the only variable that names it. It used to fall
    back to ``SKILL_PLATFORM_KEY`` — the skill *signing* key — which meant one
    operator secret silently did two unrelated jobs: anyone who could read or
    rotate the signing key could also open every sealed connector credential,
    and rotating it for a signing incident would have made the vault
    undecryptable. Two secrets, two variables.

    As with :func:`agent_core.skills.sign.platform_key`, the built-in
    development key is still right for a laptop, but only where the environment
    says it is not production.
    """
    raw = (os.getenv("VAULT_MASTER_KEY") or "").strip()
    if not raw:
        env = env_name()
        if env not in NON_PROD_ENVS:
            raise RuntimeError(
                "VAULT_MASTER_KEY is not set and APP_ENV=" + env + " is not a "
                "non-production environment " + str(sorted(NON_PROD_ENVS)) + ". "
                "Vault ciphertext must not be sealed with the built-in "
                "development key outside development. Set VAULT_MASTER_KEY."
            )
        raw = DEV_MASTER_KEY
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


def seal(plaintext: str, *, key: bytes | None = None) -> str:
    master = key or master_key()
    data = plaintext.encode("utf-8")
    nonce = os.urandom(_NONCE)
    enc_key = hmac.new(master, nonce + b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, nonce + b"mac", hashlib.sha256).digest()
    ct = bytes(a ^ b for a, b in zip(data, _stream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + ct).decode("ascii")


def open_sealed(token: str, *, key: bytes | None = None) -> str:
    master = key or master_key()
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if len(raw) < _NONCE + _TAG:
        raise ValueError("vault_ciphertext_truncated")
    nonce, tag, ct = raw[:_NONCE], raw[_NONCE : _NONCE + _TAG], raw[_NONCE + _TAG :]
    enc_key = hmac.new(master, nonce + b"enc", hashlib.sha256).digest()
    mac_key = hmac.new(master, nonce + b"mac", hashlib.sha256).digest()
    expect = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expect):
        raise ValueError("vault_mac_mismatch")
    data = bytes(a ^ b for a, b in zip(ct, _stream(enc_key, nonce, len(ct))))
    return data.decode("utf-8")
