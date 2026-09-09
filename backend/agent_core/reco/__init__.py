"""Next-Best-Offer engine — deterministic product selection.

The model does not choose the product. It never did anything else before: the
only guidance was a comma-separated list of ids inside a tool description, and
``check_product_eligibility`` was a veto that ran *after* the model had already
picked. That is backwards, and it cannot express "this customer already holds
it", "this campaign is out of quota", or "they said no to exactly this six
weeks ago".

The pipeline is a funnel of narrowing, each stage auditable on its own:

    features  →  candidates  →  eligibility veto  →  score  →  arbitrate  →  log

``recommend()`` in :mod:`agent_core.reco.engine` runs the whole thing and is the
only entry point callers need. Everything it returns has already survived every
gate, so the tool layer can hand the shortlist straight to the model and the
model's remaining job is purely linguistic.

Layout
------
``features``     the customer/call signal vector, behind a provider protocol
``candidates``   set logic: active, in-campaign, not held, not conflicting
``scoring``      the pluggable ranker (``RuleScorer`` today, ML later)
``arbitration``  policy gates — caps, cool-downs, sentiment, suppression
``decisions``    the append-only decision log that makes any of this trainable
``engine``       orchestration
``config``       tunables, read from the environment

Why the re-exports are lazy
---------------------------
``recommend`` and ``RecommendationResult`` resolve through PEP 562, the same
way ``agent_core`` itself already defers its own, and for a sharper reason than
import cost.

Importing *any* submodule runs this ``__init__`` first. Eagerly pulling
``engine`` from here therefore made the whole serving stack — including the LLM
reranker ``engine`` wires up — a prerequisite for importing ``scoring``, which
computes numbers and must not be able to reach a language model at all
(§12.1). The contract in ``tests/test_perception_boundary.py`` reported exactly
that chain:

    agent_core.reco.scoring -> agent_core.reco -> agent_core.reco.engine
      -> agent_core.reco.rerank -> azure_openai

Deferring costs nothing at runtime — the first attribute access resolves the
module and caches it in ``globals()`` — and changes no public name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    from agent_core.reco.engine import RecommendationResult as RecommendationResult
    from agent_core.reco.engine import recommend as recommend

_EXPORTS: dict[str, str] = {
    "RecommendationResult": "agent_core.reco.engine",
    "recommend": "agent_core.reco.engine",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # resolve once, then behave like a plain attribute
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
