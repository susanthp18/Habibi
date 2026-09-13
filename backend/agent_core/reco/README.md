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
2. **Live.** `RECO_MODE=live`. Offers are scored on the call and never spoken
   on it (§9.7), so there is no per-call presentation cap. Guardrails:
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

## The offer is scored on the call and never spoken on it (W12, §9.7)

This is the invariant the whole package now turns on, and until W12 it was
false. `_tool_recommend_next_offer` returned a product id, a product name, an
indicative amount, an ROI and a ready-phrased talk track, and then told the
model to *"mention this ONE product in a single short sentence with the
indicative amount"*. The close probe did the same thing by a second route,
reading `top.talk_track` straight off the result and folding it into the
`pre_close` prompt.

A promotional utterance inside a recorded collections call is three breaches at
once. It **reclassifies the entire communication as Promotional**, which then
subjects the collections call itself to the borrower's DND. It is **marketing
without a suitability finding**, and an explicit consent artefact does not cure
unsuitability. And on a delinquent borrower it is the **textbook mis-selling
fact pattern**, carrying refund plus compensation.

So the score is written to a decision row with
`chosen_channel='deferred_promotional'` and delivered later as a separate,
consented, suitability-gated promotional communication — never in the call,
never in the collections message, never in the same template.

The gate is `RecommendationResult.to_tool_payload()`, and it lives there rather
than in each caller because both mouths and every future one route through it. A
model that is never told a product name cannot be prompted, jailbroken or
flow-graphed into saying one. A scored offer and a suppressed one produce the
*identical* payload, which they must: a payload saying "there is something I am
not telling you" is one turn of pressure away from an allusion.

`present()` left the call path with it. It now belongs to the promotional
sender: `presented` means delivered on the promotional series, and consuming
campaign quota for something nobody was ever told about is how a campaign
reports reach it did not have.

## Suitability, and the audit trail (W12, §9.7)

`capture.evaluate_product_eligibility` answers *"does this borrower qualify"*
from the catalog's rules. `suitability.objection()` answers the different
question a supervisor and an inspection actually ask: **was the product
suitable for this person, who says so, and on what evidence.**

`suitability_assessments` is the record — `sql/32_offer_absorption.sql`, one row
per borrower × product, with `assessor`, `policy_version`, `verdict`,
`evidence_ref` and `expires_at`. `evidence_ref` is NOT NULL and non-empty under
a database CHECK, on the same rule the pre-registration table applies: an audit
trail whose evidence pointer is optional is a note.

**An absent finding is a refusal, not a pass**, and so is an absent *table* —
§8.12's rule about unevaluable gates, applied to a schema. The check runs per
candidate inside `_apply_eligibility`, so the reason lands in the decision log's
`excluded` map next to the eligibility vetoes and a validator can see which of
the two fired.

## One log, and the window that closes it (W12, §15.4)

`offer_decisions` is retired into `treatment_decisions` as
`action_family='offer'`. Measured on `collections` on 2026-09-10, the reason is
not tidiness: **16 rows, 9 live, all on logging contract 1, none carrying a
propensity, and zero recording a response in the log's entire history.** The
corpus is simultaneously unevaluable and unlabelled. Migration `0085` gave
`treatment_decisions` a propensity, a policy version and an explore kind and did
not give them to `offer_decisions`, and its own docstring says why that is
terminal — you can retrain on old data forever, but you can never go back and
record what the odds were.

The write is **dual for one window**: `decisions.record` writes both tables,
sharing one `OD-…` id, and `mark_presented` / `record_response` / `attach_lead`
update both. What closes the window is not a date but a ratchet —
`test_the_retired_offer_log_only_ever_loses_readers` counts references to the
old table outside alembic history and fails if the count rises. Lower the
ceiling when a reader moves; never raise it.

Two things the absorption brings on day one, both of which W11a had to repair
retroactively on the treatment side:

- **A suppressed offer is an observation.** It is written as `chosen_action='wait'`
  carrying its logged propensity, not dropped. Dropping them scores every policy
  against the population the engine had already decided to act on.
- **Legacy rows keep their contract version.** `scripts/absorb_offer_decisions.py`
  copies the 16 old rows without stamping them current, so W11a's
  equivalence-class filter keeps excluding them. A backfill that "fixed" the
  version would make sixteen rows with no propensity look like sixteen rows an
  estimator may divide by. It defaults to `--dry-run` and prints the counts.

## Silence is a label (W12, §11.5)

`POST /offers/{decisionId}/response` is the route whose absence is the
structural reason the log has zero responses: `decisionId` was produced, typed
and serialised on every recommendation, and every consumer discarded it at the
call boundary.

Almost nobody answers, so `followthrough.sweep` closes what is left after a
14-day grace — and **which** label it writes depends on a fact the log already
holds. Delivered and unanswered is `deferred`; never delivered is `not_reached`,
which is **censoring**, not refusal. Nobody was asked, so nobody declined, and
an estimator that scores the two the same is measuring the promotional series'
delivery rate and calling it demand. The sweep never writes `interested` or
`declined`: those are things a person said.

## Guarantees worth not breaking

- `recommend()` never raises.
- A scorer never sees a vetoed product.
- `suggest_amount()` always lands inside the product's ticket band, or returns
  `None` — it never invents a figure.
- Unknown facts are **absent**, not zero. A customer with no payment history is
  not ranked as though they had a bad one.
- Every invocation is logged, including suppressed and shadow ones. Those are
  the counterfactuals; without them there is no offline evaluation.
- **No product ever crosses the boundary to a text generator.** Not the id, not
  the name, not the amount, not the talk track, on any path, whatever survived
  scoring. §9.7, and it is the one guarantee here that is a legal matter rather
  than an engineering preference.
