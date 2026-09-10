"""Gate 2 — binding an evaluation to the artifact it evaluated.

``registry.check`` reads a holdout ``lift`` out of a plain mapping and refuses
the promotion when it is too small. Nothing tied that mapping to the file being
promoted, so **any JSON carrying a ``lift`` key promoted any artifact** — and
the failure that makes real is not forgery. It is an engineer who evaluates
three challengers, promotes the wrong path, and gets a green gate: the lift is
real, the artifact is not the one it describes, and every downstream record says
the model was validated.

Two things fix that, and both are here because either alone is weaker than it
looks:

**The sha binds.** The evaluation names the sha256 of the artifact it scored;
the gate recomputes that sha from the file it is about to copy into the serving
path and refuses on any difference. This is the half that catches the mistake.

**The seal authenticates.** An HMAC over the canonical evaluation body says the
numbers came from something holding ``TREATMENT_EVALUATION_KEY`` — so a report
cannot be hand-edited between production and promotion, and "the lift figure was
adjusted" stops being an unfalsifiable accusation. This is the half that makes
the record worth keeping.

Keyed exactly like :mod:`agent_core.skills.sign`, deliberately: that module
already learned that falling back to a built-in development key whenever the
real one is unset means an unconfigured production deploy verifies against a
public constant. Outside a declared non-production environment a missing key is
an error at sign and verify time, not a quietly weaker check.

The canonical encoding is ``json.dumps(..., sort_keys=True,
separators=(",", ":"), allow_nan=False)`` over the body with ``seal`` removed.
``allow_nan=False`` is not decoration: an evaluation carrying a NaN lift is
exactly the artifact the finite-value gate in :mod:`agent_core.treatment.models`
refuses, and a seal that could be computed over one would launder it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Mapping

from env_utils import NON_PROD_ENVS, env_name

#: Used only inside a declared non-production environment, and named so that a
#: grep for it in a production incident answers the question immediately.
DEV_EVALUATION_KEY = "dev-treatment-evaluation-key-not-for-prod"

#: The key that ``seal`` and ``verify`` share.
KEY_ENV = "TREATMENT_EVALUATION_KEY"

#: The field the seal lives in, and the field naming the artifact it binds to.
SEAL_FIELD = "seal"
SHA_FIELD = "artifact_sha"


class Unsealable(Exception):
    """The body cannot be canonicalised, so it cannot be sealed or verified."""


def evaluation_key() -> bytes:
    raw = (os.getenv(KEY_ENV) or "").strip()
    if raw:
        return raw.encode("utf-8")
    env = env_name()
    if env not in NON_PROD_ENVS:
        raise RuntimeError(
            f"{KEY_ENV} is not set and APP_ENV={env} is not a non-production "
            f"environment {sorted(NON_PROD_ENVS)}. A promotion evaluation "
            "cannot be verified against the built-in development key outside "
            f"development. Set {KEY_ENV}."
        )
    return DEV_EVALUATION_KEY.encode("utf-8")


def canonical(body: Mapping[str, Any]) -> str:
    """The exact bytes the seal covers. Order-independent, NaN-intolerant."""
    payload = {k: v for k, v in dict(body).items() if k != SEAL_FIELD}
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise Unsealable(str(exc)) from exc


def seal(body: Mapping[str, Any], *, key: bytes | None = None) -> str:
    """The HMAC over ``body``. Whatever ``artifact_sha`` it carries is covered."""
    material = canonical(body).encode("utf-8")
    return hmac.new(key or evaluation_key(), material, hashlib.sha256).hexdigest()


def sealed(body: Mapping[str, Any], *, key: bytes | None = None) -> dict[str, Any]:
    """``body`` with its seal attached. What an evaluation writer emits."""
    out = {k: v for k, v in dict(body).items() if k != SEAL_FIELD}
    out[SEAL_FIELD] = seal(out, key=key)
    return out


def verify(body: Mapping[str, Any], *, key: bytes | None = None) -> bool:
    """Whether ``body``'s own seal covers it. False on anything unexpected."""
    given = str(dict(body).get(SEAL_FIELD) or "")
    if not given:
        return False
    try:
        expected = seal(body, key=key)
    except Unsealable:
        return False
    return hmac.compare_digest(expected, given)


def objections(
    body: Mapping[str, Any] | None, *, artifact_sha: str, key: bytes | None = None
) -> list[str]:
    """Every reason this evaluation does not bind to ``artifact_sha``.

    Returned rather than raised, because :func:`registry.check` collects
    objections and the operator wants all of them at once — "it names a
    different artifact *and* the seal does not verify" is one round trip and two
    separate problems.
    """
    if body is None:
        return []
    named = str(dict(body).get(SHA_FIELD) or "").strip().lower()
    out: list[str] = []
    if not named:
        out.append(
            f"evaluation carries no {SHA_FIELD}, so it describes no particular "
            "artifact — a holdout lift unbound to a file is a number about "
            "something else"
        )
    elif named != (artifact_sha or "").strip().lower():
        out.append(
            f"evaluation was computed against artifact {named[:12]} but the file "
            f"being promoted is {artifact_sha[:12]}"
        )
    if not verify(body, key=key):
        out.append(
            f"evaluation {SEAL_FIELD} does not verify under {KEY_ENV} — it was "
            "produced without the key, or altered after it was produced"
        )
    return out
