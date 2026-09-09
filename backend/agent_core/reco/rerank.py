"""The LLM reranker — language, after every deterministic layer has decided.

Moved out of :mod:`agent_core.reco.models` under W9. §12.1 makes the boundary a
CI contract rather than a convention:

    forbidden: agent_core.reco.{scoring,candidates} -> azure_openai

and it was violated by construction, because ``scoring.build_scorer`` — a
factory that lives in the scoring module — imported ``models`` in order to wrap
the resolved scorer in this class, and ``models`` held the Azure call. Nothing
about the ranking arithmetic needed it; a factory did.

So the wiring moved to :mod:`agent_core.reco.engine`, which is where the
serving stack is assembled, and the class moved here. The contract is now a
property of the import graph instead of an argument about which lines in
``scoring.py`` count as ranking.

The narrow contract of the reranker itself is unchanged and is the whole
design: the model sees only offers that already cleared candidate generation,
the eligibility veto and scoring; it returns ids; any id not in the input set is
dropped and logged. It cannot introduce a product, cannot resurrect a vetoed
one, and cannot touch an amount.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from agent_core.reco.scoring import Recommender, ScoredOffer
from agent_core.reco.features import CallSignals, CustomerFeatures
from agent_core.reco.candidates import Candidate
from env_utils import env_bool

logger = logging.getLogger(__name__)


def llm_rerank_enabled() -> bool:
    return env_bool("RECO_LLM_RERANK")


class LLMReranker:
    """Reorders an approved shortlist and rewrites its talk track.

    The narrow contract is the whole design. The model sees only offers that
    already cleared candidate generation, the eligibility veto and scoring; it
    returns ids, and **any id not in the input set is dropped and logged**. It
    cannot introduce a product, cannot resurrect a vetoed one, and cannot touch
    an amount. This is the bounded, defensible answer to "just use an LLM":
    the LLM does language, the deterministic layers do selection.

    Any failure — timeout, malformed JSON, empty result — returns the base
    ranking unchanged.
    """

    def __init__(self, base: Recommender, *, top_k: int = 3) -> None:
        self._base = base
        self._top_k = max(1, top_k)
        self.name = f"llm_rerank({getattr(base, 'name', 'base')})"
        self.version = getattr(base, "version", "1.0.0")

    def score(
        self,
        features: CustomerFeatures,
        signals: CallSignals,
        candidates: Sequence[Candidate],
    ) -> list[ScoredOffer]:
        base = self._base.score(features, signals, candidates)
        if len(base) < 2:
            # Nothing to reorder. Not worth a network round trip on the audio
            # path to confirm that a one-item list is already sorted.
            return base

        head, tail = base[: self._top_k], base[self._top_k :]
        order = self._ask(head, signals)
        if not order:
            return base

        by_id = {o.product_id: o for o in head}
        reordered = [by_id.pop(pid) for pid in order if pid in by_id]
        # Anything the model omitted keeps its original relative position
        # rather than being silently dropped from the shortlist.
        reordered.extend(o for o in head if o.product_id in by_id)
        return reordered + tail

    def _ask(self, head: Sequence[ScoredOffer], signals: CallSignals) -> list[str]:
        allowed = {o.product_id for o in head}
        payload = [
            {
                "productId": o.product_id,
                "productName": o.name,
                "reasonCodes": list(o.reason_codes),
                "suggestedAmount": o.suggested_amount,
            }
            for o in head
        ]
        prompt = (
            "You are ranking pre-approved offers for a collections call. "
            "Reorder them by how relevant each is to what the customer has "
            "said in this conversation.\n\n"
            f"Conversation intents: {', '.join(signals.intents_seen) or 'none recorded'}\n"
            f"Products the customer named: {', '.join(signals.product_mentions) or 'none'}\n"
            f"Knowledge-base topics they asked about: "
            f"{', '.join(signals.kb_topics_queried) or 'none'}\n"
            f"Current sentiment: {signals.sentiment_current:+.2f}\n\n"
            f"Offers: {json.dumps(payload)}\n\n"
            'Reply with JSON only: {"order": ["productId", ...]}. '
            "Use only the product ids given. Do not invent products, do not "
            "add commentary, do not change any amount."
        )

        try:
            import azure_openai

            raw = azure_openai.chat_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_completion_tokens=200,
            )
            parsed = json.loads(_strip_fence(raw))
            order = [str(pid) for pid in (parsed.get("order") or [])]
        except Exception:
            logger.warning("LLM rerank failed — keeping the base order", exc_info=True)
            return []

        rejected = [pid for pid in order if pid not in allowed]
        if rejected:
            # The one failure mode that matters: the model naming a product
            # nobody approved. Dropped here, and loud, because a silent drop
            # would hide a prompt-injection attempt as easily as a typo.
            logger.warning("LLM rerank returned unapproved product ids %s — dropped", rejected)
        return [pid for pid in order if pid in allowed]


def _strip_fence(raw: str) -> str:
    """Tolerate ```json fences, which models add regardless of instructions."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
