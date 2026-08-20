"""The bounded LLM layer — and the boundary is the whole design.

This is where a language model is allowed to touch a collections decision, and
the list of things it may do is short: **reorder actions that have already
cleared candidate generation, every veto and the scorer, and write one sentence
of rationale for the human reading the queue.**

It may not introduce an action, resurrect a vetoed one, change a channel, move
an instant, alter an expected value, or put a number on the screen that the
deterministic layers did not compute. Every one of those is enforced here by
dropping the offending output and logging it, not by asking the model nicely in
a prompt — a prompt is a request, and the failure mode being guarded against is
precisely a model that does not honour requests, whether through error or
through text a borrower typed into a WhatsApp thread.

Any failure at all — timeout, malformed JSON, empty result, an unknown action —
returns the deterministic ranking unchanged. That is the property that makes it
safe to leave switched on.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Sequence

from agent_core.treatment import actions as A
from agent_core.treatment.config import Costs, Policy
from agent_core.treatment.features import AccountFeatures, Trigger
from agent_core.treatment.scoring import Candidate, Recommender, ScoredAction

logger = logging.getLogger(__name__)

MAX_WHY_CHARS = 240
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fence(raw: str) -> str:
    return _FENCE.sub("", (raw or "").strip())


def _digits(text: str) -> set[str]:
    """Digit sequences, normalised so 1,150 and 1150 compare equal."""
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text or "")}


class LLMReranker:
    """Reorders an approved shortlist and drafts one line of rationale."""

    def __init__(self, base: Recommender, *, top_k: int = 3) -> None:
        self._base = base
        self._top_k = max(1, top_k)
        self.name = f"llm_rerank({getattr(base, 'name', 'base')})"
        self.version = getattr(base, "version", "1.0.0")

    def score(
        self,
        features: AccountFeatures,
        trigger: Trigger,
        candidates: Sequence[Candidate],
        *,
        now: datetime,
        policy: Policy,
        costs: Costs,
    ) -> list[ScoredAction]:
        base = self._base.score(
            features, trigger, candidates, now=now, policy=policy, costs=costs
        )
        if len(base) < 2:
            # A one-item list is already sorted. Not worth a network round trip
            # to confirm it.
            return base

        head, tail = base[: self._top_k], base[self._top_k :]
        order, why = self._ask(head, features, trigger, now=now)
        if not order:
            return base

        by_key = {s.action: s for s in head}
        reordered = [by_key.pop(k) for k in order if k in by_key]
        # Anything the model omitted keeps its original relative position
        # rather than being silently dropped from the shortlist.
        reordered.extend(s for s in head if s.action in by_key)

        if why and reordered:
            from dataclasses import replace

            reordered[0] = replace(reordered[0], explanation=why)
        return reordered + tail

    # ------------------------------------------------------------------ model

    def _ask(
        self,
        head: Sequence[ScoredAction],
        features: AccountFeatures,
        trigger: Trigger,
        *,
        now: datetime,
    ) -> tuple[list[str], str | None]:
        allowed = {s.action for s in head}
        payload = [
            {
                "action": s.action,
                "channel": s.channel,
                "when": s.at.isoformat() if s.at else None,
                "expectedValueInr": round(s.expected_value, 2),
                "chanceOfReaching": round(s.p_reach, 2),
                "reasonCodes": list(s.reason_codes),
                "timing": s.timing_rationale,
            }
            for s in head
        ]
        payload_json = json.dumps(payload)
        context = {
            "bucket": features.bucket,
            "dpd": features.dpd,
            "trigger": trigger.kind,
            "triggerAgeHours": (
                round(trigger.age_hours(now), 1) if trigger.age_hours(now) else None
            ),
            "promisesKept": features.promises_kept,
            "promisesBroken": features.promises_broken,
            "touchesToday": features.touches_today,
            "openDisputes": features.open_dispute_count,
        }

        prompt = (
            "You are ordering pre-approved collections actions for one overdue "
            "borrower account at an Indian lender. Every action listed has "
            "already passed the compliance gates; your only job is to put them "
            "in the order most likely to resolve this account without "
            "irritating the borrower.\n\n"
            f"Account context: {json.dumps(context)}\n"
            f"Approved actions: {payload_json}\n\n"
            'Reply with JSON only: {"order": ["action", ...], "why": "one short '
            'sentence for the collections agent reading this queue"}.\n'
            "Use only the action keys given. Do not invent actions, do not "
            "change any channel, time or amount, and do not put any number in "
            '"why" that is not already in the data above.'
        )

        try:
            import azure_openai

            raw = azure_openai.chat_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_completion_tokens=250,
            )
            parsed = json.loads(_strip_fence(raw))
            order = [str(k).strip() for k in (parsed.get("order") or [])]
            why = str(parsed.get("why") or "").strip()
        except Exception:
            logger.warning(
                "treatment rerank failed — keeping the deterministic order", exc_info=True
            )
            return [], None

        rejected = [k for k in order if k not in allowed]
        if rejected:
            # The failure that matters: a model naming an action nobody
            # approved. Dropped here, and loudly — a silent drop would hide a
            # prompt-injection attempt as readily as a typo, and the borrower's
            # own words reach this model's context through the account summary.
            logger.warning(
                "treatment rerank returned unapproved actions %s — dropped", rejected
            )
        order = [k for k in order if k in allowed]

        return order, self._safe_why(why, payload_json, context)

    def _safe_why(self, why: str, payload_json: str, context: dict) -> str | None:
        """Keep the sentence only if it invents no figures.

        Reordering is checkable against a set of keys. Free text is not, so the
        one property worth enforcing is the one that causes real harm: a number
        on a collections screen that nothing computed. An agent reads "₹4,200
        outstanding" as fact and repeats it to the borrower.
        """
        if not why:
            return None
        if len(why) > MAX_WHY_CHARS:
            why = why[:MAX_WHY_CHARS].rstrip()
        known = _digits(payload_json) | _digits(json.dumps(context))
        invented = _digits(why) - known
        if invented:
            logger.warning(
                "treatment rerank rationale invented figures %s — dropped", sorted(invented)
            )
            return None
        return why
