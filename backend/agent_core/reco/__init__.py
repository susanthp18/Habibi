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
"""

from agent_core.reco.engine import recommend, RecommendationResult

__all__ = ["recommend", "RecommendationResult"]
