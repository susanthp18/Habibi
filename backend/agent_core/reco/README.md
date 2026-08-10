# Next-Best-Offer engine

Deterministic product selection for upsell / cross-sell. The LLM does not choose
the product — it receives a shortlist that has already passed every gate, and
its remaining job is purely linguistic.

## Why it exists

Before this, product choice was the model's. The only guidance was a
comma-separated list of ids inside a tool description, and
`check_product_eligibility` was a veto that ran *after* the model had already
picked. That ordering cannot express "they already hold it", "this campaign is
out of quota", or "they refused exactly this six weeks ago" — and a model only
has to hallucinate one plausible slug (the ids are guessable English) to pitch
something nobody approved.

## Pipeline

```
features → candidates → eligibility veto → score → arbitrate → log
```

| Stage | Module | Answers |
|---|---|---|
| Features | `features.py` | what do we know about this customer *and this call*? |
| Candidates | `candidates.py` | what is even offerable? (active, in-campaign, not held, no conflict) |
| Veto | `engine.py` → `capture.evaluate_product_eligibility` | may we offer it? |
| Score | `scoring.py` | which one is best? |
| Arbitrate | `arbitration.py` | should we say anything at all? |
| Log | `decisions.py` | what did we decide, and why? |

Scoring answers *which*; arbitration answers *whether*. They are separate on
purpose: the moment a compliance rule becomes a score penalty, someone can tune
it away while chasing conversion.

## Entry point

```python
from agent_core.reco import recommend

result = recommend(
    customer_id="vikram-rao",
    interaction_id="IX-123",       # optional, but the in-call signals need it
    channel="voice",               # voice | whatsapp
    live=CallSignals(...),         # what only the running call knows
)
result.suppressed        # True → say nothing about products
result.top               # best ScoredOffer, or None
result.to_tool_payload() # model-facing shape
```

`recommend()` **never raises** — it runs on the audio path of a live call, and
"no offer" is always a valid outcome where an exception is not.

## Configuration

All read from the environment at call time, so a change takes effect without a
restart.

| Variable | Default | Meaning |
|---|---|---|
| `RECO_MODE` | `shadow` | `off` \| `shadow` \| `live` |
| `RECO_SCORER` | `rule` | which `Recommender` implementation |
| `RECO_MIN_SCORE` | `0.35` | below this, say nothing |
| `RECO_MAX_OFFERS` | `2` | shortlist length |
| `RECO_MAX_PER_CALL` | `1` | offers presented per conversation |
| `RECO_MAX_PER_CUSTOMER_30D` | `3` | frequency cap |
| `RECO_DECLINE_COOLDOWN_DAYS` | `90` | re-pitch cool-down after a refusal |
| `RECO_SENTIMENT_FLOOR` | `-0.15` | below this, never pitch |
| `RECO_REQUIRE_COMMITMENT` | `true` | no offer before a PTP/callback exists |
| `RECO_W_AFFINITY` | `0.20` | complementarity to held products |
| `RECO_W_AFFORDABILITY` | `0.20` | headroom vs ticket band |
| `RECO_W_CREDIT` | `0.15` | worst DPD + punctuality |
| `RECO_W_INTENT` | `0.20` | in-call signal (strongest, and free) |
| `RECO_W_SENTIMENT` | `0.10` | receptiveness |
| `RECO_W_CAMPAIGN` | `0.10` | campaign priority × product margin |
| `RECO_W_FATIGUE` | `0.05` | subtracted after normalisation |

Weights live in config rather than code because tuning a recommender is an
operational act, not a release.

**`shadow` is the default.** A new recommender scores and logs everything and
says nothing, through the same code path live uses — so what ships is what was
measured. An unrecognised `RECO_MODE` degrades to `shadow`, not `off`: a typo
must not silently stop collecting the data the engine learns from.

## Rollout

1. **Shadow (2 weeks).** `RECO_MODE=shadow`. Watch coverage (% calls with ≥1
   approved offer), the score distribution, and the suppression breakdown.
2. **Live, capped.** `RECO_MODE=live`, `RECO_MAX_PER_CALL=1`. Guardrails:
   complaint rate, average handle time, sentiment delta, escalation rate. Any
   regression reverts.
3. **Learn.** Once ~2–3k labelled leads exist in `offer_decisions`, train a
   `PropensityScorer` against the logged feature snapshots and add it behind
   `RECO_SCORER` with automatic fallback to `RuleScorer`.

## Extending

**A different data source** — implement `FeatureProvider.build()` against your
schema and pass `provider=` to `recommend()`. Nothing downstream changes;
everything depends on `CustomerFeatures`/`CallSignals`, never on a table name.

**A different ranker** — implement the `Recommender` protocol (`name`,
`version`, `score()`) and register it in `scoring.build_scorer`. A scorer cannot
add a product, cannot overturn a veto, and cannot reach the database. That is
what makes swapping one safe.

**An LLM re-ranker** belongs here too, and only here: it may reorder the
already-approved top-K and draft the phrasing. It must not be able to introduce
a product id that did not come out of `candidates` + veto.

## Guarantees worth not breaking

- `recommend()` never raises.
- A scorer never sees a vetoed product.
- `suggest_amount()` always lands inside the product's ticket band, or returns
  `None` — it never invents a figure.
- Unknown facts are **absent**, not zero. A customer with no payment history is
  not ranked as though they had a bad one.
- Every invocation is logged, including suppressed and shadow ones. Those are
  the counterfactuals; without them there is no offline evaluation.
