"""API key pooling — free-tier quota that survives a demo.

A free Cartesia account is roughly 27 minutes of speech a month. One account
does not survive a demo day, so the keys arrive as a pool and the runtime
rotates across them.

Two rules make the rotation safe, and both exist because the obvious
implementation is wrong:

**Rotation is per SESSION, never per request.** Round-robining every synthesis
call across five accounts means one sentence can be voiced by account A and the
next by account B. The voices are not bit-identical across accounts (different
warm-up state, occasionally different model revision), so the caller hears a
seam mid-turn. A session holds its key until the session ends.

**A 429 retires the key, it does not fail the call.** Quota exhaustion is the
expected end state of a free key, not an error condition. The pool marks it
retired, hands the session a fresh key, and the call continues. Only when every
key is retired does this raise — and that is a real error the binding layer
answers by failing over to the next provider in the chain, not by dropping audio.

Retirement is process-scoped by default. Free-tier quota is monthly, so a key
that 429s will keep 429ing for hours; re-probing it every few minutes spends
latency on a call to learn something already known. ``cooldown_s`` exists for
paid keys, where a 429 is rate-limiting rather than exhaustion.

**Rotation lives here, not in the adapters.** :func:`call_with_rotation` owns
the acquire → call → retire-on-key-fault → retry loop. It was previously open-
coded in the Fish and OpenRouter clients and simply absent from the Cartesia,
Deepgram and ElevenLabs ones, so three providers held pools they could never
rotate: the first key 429'd and every later call re-acquired the same dead key.
A new provider added against this helper gets rotation without anyone
remembering to add it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal, TypeVar

logger = logging.getLogger(__name__)

Strategy = Literal["round_robin", "least_used", "sticky_per_tenant"]

#: Sentinel for "retired for the life of the process".
NEVER = float("inf")


class NoKeysAvailable(RuntimeError):
    """Every key in the pool is retired, or none were configured.

    Callers must treat this as a provider outage and fail over, never as a
    reason to synthesize silence.
    """


class KeyRejected(RuntimeError):
    """The *credential* was refused — retire it and try the next key.

    Deliberately narrower than "the request failed". A 400 means our payload is
    malformed, and every key in the pool will refuse it identically; treating
    that as a key fault would burn the whole pool to learn nothing and would
    report five healthy keys as retired. Raise this only for statuses that
    indict the key itself.
    """

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


#: HTTP statuses that indict the credential rather than the request.
#:
#: ``401`` / ``403`` — revoked, or missing a scope. Not hypothetical: the
#:     ElevenLabs key in this deployment ships without ``voices_read`` and 401s
#:     every call, which is indistinguishable from an outage until the key is
#:     named as the cause.
#: ``402`` — out of credit. Fish bills API credit separately from platform
#:     credit, so a funded account still 402s on synthesis.
#: ``429`` — quota or rate limit. The expected end state of a free-tier key.
KEY_FAULT_STATUSES: frozenset[int] = frozenset({401, 402, 403, 429})


def is_key_fault(status: int) -> bool:
    """Whether ``status`` should retire the key rather than fail the request."""
    return status in KEY_FAULT_STATUSES


def reason_for_status(status: int) -> str:
    """A short retirement reason, shown per-key on the Integrations screen."""
    return {
        401: "401 unauthorized — key revoked or wrong scope",
        402: "402 payment required — no API credit",
        403: "403 forbidden — key lacks the required scope",
        429: "429 quota or rate limit",
    }.get(status, f"HTTP {status}")


@dataclass
class _Key:
    value: str
    uses: int = 0
    retired_until: float = 0.0
    last_error: str = ""

    def available(self, now: float) -> bool:
        return self.retired_until <= now

    @property
    def tail(self) -> str:
        """Last 4 chars — enough to identify a key in a log without leaking it."""
        return self.value[-4:] if len(self.value) >= 4 else "????"


@dataclass
class PoolStats:
    provider: str
    total: int
    available: int
    retired: int
    sessions_bound: int
    keys: list[dict[str, object]] = field(default_factory=list)


class KeyPool:
    """One provider's keys, with sticky session binding and retirement."""

    def __init__(
        self,
        provider: str,
        keys: list[str],
        *,
        strategy: Strategy = "round_robin",
        cooldown_s: float | None = None,
    ) -> None:
        self.provider = provider
        self.strategy: Strategy = strategy
        # None → retire for the process. See module docstring.
        self.cooldown_s = cooldown_s
        self._keys = [_Key(value=k) for k in keys]
        self._cursor = 0
        self._sessions: dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ read

    def __len__(self) -> int:
        return len(self._keys)

    def stats(self) -> PoolStats:
        now = time.monotonic()
        with self._lock:
            return PoolStats(
                provider=self.provider,
                total=len(self._keys),
                available=sum(1 for k in self._keys if k.available(now)),
                retired=sum(1 for k in self._keys if not k.available(now)),
                sessions_bound=len(self._sessions),
                keys=[
                    {
                        "tail": k.tail,
                        "uses": k.uses,
                        "retired": not k.available(now),
                        "lastError": k.last_error,
                    }
                    for k in self._keys
                ],
            )

    # ----------------------------------------------------------------- write

    def acquire(self, session_id: str | None = None, *, tenant_id: str | None = None) -> str:
        """Return a key, sticky to ``session_id`` when one is given.

        Raises :class:`NoKeysAvailable` when nothing is left — the caller fails
        over to the next provider rather than degrading the call.
        """
        now = time.monotonic()
        with self._lock:
            if not self._keys:
                raise NoKeysAvailable(
                    f"{self.provider}: no keys configured "
                    f"(set {self.provider.upper()}_API_KEYS)"
                )

            # Sticky: a session keeps its key unless that key has since retired.
            if session_id is not None:
                idx = self._sessions.get(session_id)
                if idx is not None and self._keys[idx].available(now):
                    self._keys[idx].uses += 1
                    return self._keys[idx].value

            idx = self._pick(now, tenant_id=tenant_id)
            if idx is None:
                raise NoKeysAvailable(
                    f"{self.provider}: all {len(self._keys)} keys retired"
                )

            self._keys[idx].uses += 1
            if session_id is not None:
                self._sessions[session_id] = idx
            return self._keys[idx].value

    def retire(self, key: str, *, reason: str = "quota") -> None:
        """Take a key out of rotation and unbind every session holding it."""
        now = time.monotonic()
        with self._lock:
            for idx, k in enumerate(self._keys):
                if k.value != key:
                    continue
                k.retired_until = NEVER if self.cooldown_s is None else now + self.cooldown_s
                k.last_error = reason
                # Unbind sessions so their next acquire() picks a live key
                # instead of re-checking this one on every turn.
                for sid in [s for s, i in self._sessions.items() if i == idx]:
                    self._sessions.pop(sid, None)
                logger.warning(
                    "provider key retired · provider=%s · key=…%s · reason=%s · remaining=%d",
                    self.provider,
                    k.tail,
                    reason,
                    sum(1 for x in self._keys if x.available(now)) - 1,
                )
                return

    def release(self, session_id: str) -> None:
        """Drop a session's binding. Call on session end so the map cannot grow."""
        with self._lock:
            self._sessions.pop(session_id, None)

    # --------------------------------------------------------------- picking

    def _pick(self, now: float, *, tenant_id: str | None) -> int | None:
        live = [i for i, k in enumerate(self._keys) if k.available(now)]
        if not live:
            return None
        if self.strategy == "least_used":
            return min(live, key=lambda i: self._keys[i].uses)
        if self.strategy == "sticky_per_tenant" and tenant_id:
            return live[hash(tenant_id) % len(live)]
        # round_robin — advance over the live subset only.
        self._cursor = (self._cursor + 1) % len(live)
        return live[self._cursor]


# --------------------------------------------------------------------- registry

_POOLS: dict[str, KeyPool] = {}
_POOLS_LOCK = threading.Lock()


def _parse_keys(raw: str | None) -> list[str]:
    """Comma-separated, stripped, de-duplicated, order preserved.

    De-duplication matters: pasting the same key twice would otherwise double
    its apparent quota and make the "keys remaining" number in the UI a lie.
    """
    seen: list[str] = []
    for part in (raw or "").split(","):
        k = part.strip()
        if k and k not in seen:
            seen.append(k)
    return seen


#: Providers whose env prefix is not simply the slug upper-cased. Azure's
#: speech credentials are shared with the TTS/STT code that predates this
#: module, so the registry points at that prefix rather than renaming a var
#: half the codebase already reads.
_ENV_PREFIX: dict[str, str] = {"azure": "AZURE_SPEECH"}


def _key_env(slug: str) -> str:
    return _ENV_PREFIX.get(slug, slug.upper())


#: Cooldown applied to a single-key pool when nothing is configured explicitly.
DEFAULT_SINGLE_KEY_COOLDOWN_S = 900.0


def _default_cooldown(key_count: int) -> float | None:
    """Retirement policy for a pool of ``key_count`` keys.

    Multi-key pools retire permanently, which is the free-tier assumption in the
    module docstring: monthly quota does not come back, and the pool self-heals
    because rotation still has somewhere to go.

    A **single-key pool has nowhere to rotate to**, so a permanent retirement is
    not a rotation — it is switching the provider off for the life of the
    process. A transient 429 from Azure would take the voice pipeline down until
    someone restarted it. A bounded cooldown costs one retry's latency after the
    window and recovers by itself, which is strictly better than that, so it is
    the default here and ``<PREFIX>_POOL_COOLDOWN_S`` overrides both cases.
    """
    return None if key_count > 1 else DEFAULT_SINGLE_KEY_COOLDOWN_S


def _read_cooldown(env: str, key_count: int) -> float | None:
    raw = (os.getenv(f"{env}_POOL_COOLDOWN_S") or "").strip()
    if not raw:
        return _default_cooldown(key_count)
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid %s_POOL_COOLDOWN_S=%r — using the default", env, raw)
        return _default_cooldown(key_count)
    # <= 0 is the explicit way to ask for permanent retirement.
    return None if value <= 0 else value


def get_pool(provider: str) -> KeyPool:
    """Pool for ``provider``, built once per process from the environment.

    Reads ``<PREFIX>_API_KEYS`` (falling back to ``_API_KEY`` / ``_KEY``) and
    ``<PREFIX>_POOL_STRATEGY``.
    """
    slug = provider.strip().lower()
    with _POOLS_LOCK:
        pool = _POOLS.get(slug)
        if pool is not None:
            return pool
        env = _key_env(slug)
        # Pooled form first, then the two single-key spellings already in use.
        # Azure's key predates this module and is AZURE_SPEECH_KEY, so a lookup
        # that only knew "<ENV>_API_KEY" left the default provider with an empty
        # pool — and an empty pool for the default is a dead voice pipeline.
        keys: list[str] = []
        for var in (f"{env}_API_KEYS", f"{env}_API_KEY", f"{env}_KEY"):
            keys = _parse_keys(os.getenv(var))
            if keys:
                break
        strategy = (os.getenv(f"{env}_POOL_STRATEGY") or "round_robin").strip().lower()
        if strategy not in ("round_robin", "least_used", "sticky_per_tenant"):
            logger.warning(
                "unknown %s_POOL_STRATEGY=%r — falling back to round_robin", env, strategy
            )
            strategy = "round_robin"
        cooldown = _read_cooldown(env, len(keys))
        pool = KeyPool(slug, keys, strategy=strategy, cooldown_s=cooldown)  # type: ignore[arg-type]
        _POOLS[slug] = pool
        logger.info(
            "key pool ready · provider=%s · keys=%d · strategy=%s · cooldown=%s",
            slug,
            len(keys),
            strategy,
            "permanent" if cooldown is None else f"{cooldown:g}s",
        )
        return pool


T = TypeVar("T")


def call_with_rotation(
    provider: str,
    fn: Callable[[str], T],
    *,
    session_id: str | None = None,
    tenant_id: str | None = None,
    attempts: int | None = None,
) -> T:
    """Run ``fn(key)``, retiring the key and retrying when the key is at fault.

    ``fn`` signals a spent or invalid credential by raising :class:`KeyRejected`;
    anything else propagates untouched, because a malformed request is not
    something a different key fixes.

    ``attempts`` defaults to one shot per key, so a fully-spent pool costs a
    single pass and then raises :class:`NoKeysAvailable` — which the binding
    layer answers by failing over to the next provider in the chain, not by
    dropping audio.
    """
    pool = get_pool(provider)
    budget = attempts if attempts is not None else max(1, len(pool))
    last: KeyRejected | None = None

    for attempt in range(budget):
        # Re-acquired every pass: retire() unbinds the sessions holding a dead
        # key, so the next acquire() is what hands out the replacement.
        key = pool.acquire(session_id, tenant_id=tenant_id)
        try:
            return fn(key)
        except KeyRejected as exc:
            last = exc
            pool.retire(key, reason=exc.reason)
            logger.warning(
                "key rejected, rotating · provider=%s · attempt=%d/%d · reason=%s",
                provider,
                attempt + 1,
                budget,
                exc.reason,
            )

    raise NoKeysAvailable(
        f"{provider}: every key rejected after {budget} attempt(s)"
        + (f" — last: {last.reason}" if last else "")
    )


def release_session(session_id: str) -> None:
    """Drop ``session_id`` from every pool. Call once when a session ends.

    Without this the sticky-binding map is append-only for the life of the
    process: one entry per call, per provider, never reclaimed.
    """
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
    for pool in pools:
        pool.release(session_id)


def all_stats() -> list[PoolStats]:
    """Every pool built so far — the Integrations screen reads this."""
    with _POOLS_LOCK:
        return [p.stats() for p in _POOLS.values()]


def reset_pools() -> None:
    """Drop every cached pool. Tests only — the environment is read once."""
    with _POOLS_LOCK:
        _POOLS.clear()
