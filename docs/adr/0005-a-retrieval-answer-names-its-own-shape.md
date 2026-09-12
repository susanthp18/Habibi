# A retrieval answer names its own shape, and `confident` means answerable

---
Status: accepted
---

`search_knowledge_base` can return two completely different things. A **passage**
answer is document text retrieved by similarity. A **catalog** answer is the list of
products the corpus covers, assembled without any search at all — it exists because
*"what do you sell?"* has no passage to find, and the caller's own words score 0.389
against a corpus that has no document about the shape of itself.

Both arrived at the model in the same envelope, with `mode` dropped by both channel
adapters, so nothing downstream could tell them apart. A catalog row is

```json
{"docTitle": "Travel Protect360", "docType": "catalog",
 "snippet": "Travel Protect360", "score": null}
```

`confident` was `bool(products)` on that branch and `bool(results)` on the other —
in both cases "the list is non-empty", which a row whose snippet is its own title
satisfies. `confident: true` selected the directive *"Answer ONLY from these
snippets"*, and the model was asked to answer a question about travel-insurance
benefits from a product name. It refused, three turns running, and it was right to.
The glossary already states the rule that was broken: **a gate never reports green
for a check it did not run.**

## Decision

Three changes, and one of them is the load-bearing one.

1. **A catalog plan scoped to one product also retrieves passages, and merges.**
   Unscoped, it still skips retrieval — that case is real.
2. **`confident` means at least one row carries text that is not its own title**
   (`kb.answerable`). Same definition on both branches.
3. **One owner builds the model-facing payload** (`kb.llm_payload`), carrying `mode`
   and `products`, with the answer policy derived from the shape.

The first is load-bearing because **the planner is not stable on this boundary.**
Over repeated runs of identical input at temperature 0, cases flip between `passage`
and `catalog`; `scripts/eval_retrieval.py --plan --repeat N` reports which. You
cannot tune a coin flip. So the fix is not to make the verdict right, it is to make
both verdicts lead somewhere useful.

## Considered options

**Tune the planner prompt until `catalog` stops firing on passage questions.**
Rejected on the measurement above. It also fails on its own terms: *"i am looking
for travel insurance"* is a genuinely ambiguous utterance, and a system that has to
guess right about it is more fragile than one where guessing wrong costs nothing.

**Delete catalog mode and always retrieve.** Tempting, and wrong for the case it was
built for. The module docstring records it: retrieval against "what plans are
available" returned exclusions from an unrelated product, and no threshold anywhere
would have helped, because the answer is the *shape* of the corpus rather than
anything in it.

**Keep two envelopes and let each adapter branch.** Rejected as ADR-0001 one level
down. Two formulas for one payload is how two formulas disagree, and these already
had: text dropped `topScore` and `latencyMs`, voice dropped `logId` and renamed
`docTitle`, and both dropped `mode`.

**Gate on the retrieval score instead.** Already tried and already removed, for
reasons kept in the source: the absolute top score predicts retrieval success at
AUC 0.548 scoped and 0.364 unscoped. `margin` (AUC 0.975 scoped) is reported but
still not enforced — it is not scale-free across query types, so a threshold needs
calibrating on real traffic first.

## Consequences

**A catalog answer now reaches the KB-gap screen.** Gap capture sat after the
catalog short-circuit and therefore never fired for it, so the single best signal
that the corpus is missing something — a product question that could not be
answered — was the one signal never recorded. The screen, the gap→FAQ link and
`POST /kb/gaps/{id}/link` were all already built and starved.

**`prefer_policy` no longer decides the topic.** It was the first term of
`wants_exclusions`, which suppressed `wants_coverage` entirely and then reserved
`top_k - 1` of `top_k` slots for policy documents. Measured, same query, same index:

```
retrieve("Travel Protect360 benefits")                       5/5 benefits, 0.649-0.692
retrieve("Travel Protect360 benefits", prefer_policy=True)   0/5 — "Discounts offered",
                                                             "Promotion Terms and Conditions"
```

`topic` now carries that meaning explicitly and is part of the result-cache key;
`prefer_policy` keeps only the wider candidate pool. Voice sets `prefer_policy` to
pick a *corpus*, and was silently getting exclusions ranking for every question on a
scoped node.

**One test changed its mind in public.** `test_what_products_do_you_have_is_answered_from_the_corpus`
asserted `confident is True` for a catalog answer, on the reasoning that the product
list is as authoritative as the knowledge base. True, and beside the point:
`confident` is not a claim about provenance, it is what selects the directive the
model is given. The assertion now reads `is False`, with the reasoning recorded next
to it.

**`answerable` is a structural check, not a quality one.** It catches "these rows
contain no text", which is the failure that shipped. It does not catch "these rows
contain text that does not answer the question" — that judgment stays where the
passages are actually read, in the answer policy, following the Sufficient Context
result (extra context makes a model *less* willing to abstain, so abstention has to
be asked for).

**`scripts/eval_retrieval.py --plan` is the regression net**, and it deliberately
computes answerability from the payload rather than reading the `confident` field.
A harness that trusts the field under test cannot fail when that field lies, which
is exactly how this shipped.
