"""Provider registry — speech and LLM vendors as a binding, not a constant.

Four modules, in dependency order:

``registry``
    The capability matrix. What each (provider, kind, model) can actually do,
    with ``service_class`` paths read off the installed Pipecat package.
``pool``
    API key pooling. Session-sticky rotation and 429 retirement, so free-tier
    quota survives a demo without seaming a caller's audio mid-turn.
``persist``
    Seed → database, and the binding CRUD the Agent Studio screen writes.
``factory``
    Binding → a live Pipecat service, with an explicit failover chain and no
    silent default.

The rule that shapes all four: **resolution failing is an error, not a reason to
substitute something plausible.** See ``multilingual-architecture.md`` §3.
"""

from __future__ import annotations

from agent_core.providers.factory import (
    NoBindingError,
    ProviderUnavailable,
    ResolvedBinding,
    build,
    build_first_available,
    resolve_chain,
)
from agent_core.providers.pool import KeyPool, NoKeysAvailable, all_stats, get_pool
from agent_core.providers.registry import (
    SEED,
    SEED_BY_SLUG,
    ModelSpec,
    ProviderSpec,
    configured_providers,
    find_model,
    model_specs,
)

__all__ = [
    "SEED",
    "SEED_BY_SLUG",
    "KeyPool",
    "ModelSpec",
    "NoBindingError",
    "NoKeysAvailable",
    "ProviderSpec",
    "ProviderUnavailable",
    "ResolvedBinding",
    "all_stats",
    "build",
    "build_first_available",
    "configured_providers",
    "find_model",
    "get_pool",
    "model_specs",
    "resolve_chain",
]
