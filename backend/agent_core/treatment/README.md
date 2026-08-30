# Next-best-treatment engine

Decides **what should happen to a delinquent account, and when** — silence, a
mandate re-presentment, an EMI date change, SMS, WhatsApp, a bot call, an agent
call, a field visit or a statutory notice — and does it as a gated pipeline
rather than as prompt text.

Two of those nine reach nobody, and that is the difference between asking *"who
should we call?"* and asking *"what intervention should we make, if any?"*. See
**The action space** below.

Roadmap items **P3** (the decision) and **P5** (the loop that makes it a
ladder). Sits on top of P6's contact cap, and is what P4, P8 and P9 hang off.

## Why it is not "ask the model what to do"

The model is not qualified to decide, and the reason is not that it is unwise.
It is that the decision is bounded by rules a lender is *liable* for: RBI's
08:00–19:00 calling window, DND and channel opt-out, a cross-channel frequency
cap, cooling-off, hardship, an open dispute, a regulatory complaint, a matter
with legal, and the separation between collecting a debt and selling a product.
Those are not preferences to be weighed; they are conditions that must hold. A
system that can be argued out of one of them by a sufficiently sympathetic
transcript is a system that will be.

So the model's job here is language and ordering, and everything upstream of it
is arithmetic and rules — the same division reco draws, for the same reason.

## Pipeline

```
features → candidates (timing) → veto → score → arbitrate → explore → log → [enact]
```

**Exploration is last, and that is the architectural boundary.** It sees only
actions that already cleared every gate — statutory, client, customer, value
floor, budget reserve — so it decides *which permitted thing happens*, never
*whether a forbidden one does*. Randomising between WhatsApp-now and
bot-call-tomorrow costs almost nothing and is the only way to learn the ladder;
randomising and then checking compliance is experimenting on borrowers.

| Stage | Module | Answers |
|---|---|---|
| Features | `features.py` | what do we know about this account, and can we reach them? |
| Candidates | `timing.py` | *when* would each action actually happen? |
| Veto | `policy.py` → `contact_policy.evaluate` | may we, at that instant? |
| Score | `scoring.py` | what is each one worth, in rupees? |
| Rerank | `rerank.py` | *(optional)* reorder the approved list, draft one line |
| Arbitrate | `arbitration.py` | should anything happen at all? |
| Log | `decisions.py` | what did we decide, and why not the others? |
| Enact | `enact.py` | live mode only, and the gate runs again at send time |
| Attribute | `followthrough.py` | what did that attempt actually produce? |
| Re-decide | `followthrough.py` | the case is still open — what next? |

**Timing comes before the veto on purpose.** Asking "may we dial?" at 02:00
answers no for every borrower alive. Asking "may we dial at the first moment we
actually would?" answers the question the engine exists for — and it is what
lets `WhatsApp now` beat `agent call at 08:00 tomorrow` without either being
special-cased.

## The score is in rupees

```
EV  =  exposure × recovery_fraction × p(reach) × p(resolve | reach) × decay(delay)
       − cost(action)
       − fatigue(intrusiveness, touches already spent today)
```

Three consequences worth stating:

- **`wait` scores exactly 0**, so every action has to beat silence to be
  chosen. A dimensionless score cannot express that without an arbitrary
  threshold pretending to be one.
- **Cost is inside the model.** A ₹1,150 field visit and a ₹0.18 SMS are two
  amounts of money, not two points on a preference curve.
- **The number is arguable.** A collections head can disagree with "an agent
  call is worth ₹68 of expected recovery on this account". Nobody can
  meaningfully disagree with "0.62".

`decay` applies to the *planned* delay only, never to how old the event already
is. Decaying by the event's age too would push every stale account below the
floor and the engine would fall silent on exactly the borrowers who most need a
decision — the opposite of the behaviour this product exists to fix.

**Every prior in `scoring.py` is a planning figure and is wrong on day one.**
They are logged per decision precisely so a fortnight of shadow traffic replaces
them with measured ones.

## The loop (P5)

One decision per event is advisory. `followthrough.py` is what makes it a
ladder — *reminder → bot retry → human → field* — by closing the circle:

**Attribution.** Every enacted decision gets an `outcome`. Payment beats a
promise beats a connection beats silence, and an attempt is only called
unanswered after a grace period sized to the channel — a follow-up sitting in an
agent's queue is not a no-answer an hour later. This is the training label the
corpus has no other way to get.

Shadow decisions are attributed too, and only ever as `paid` / `ptp` /
`superseded` — never `no_answer`, because nobody asked. A plan the engine made,
nobody carried out, on an account that paid anyway is **the counterfactual**: the
only evidence that would ever say the engine is reallocating spend rather than
earning it.

**Re-decision.** A case is `(customer, trigger kind, trigger ref)` — one bounce,
one broken promise. When the last attempt didn't resolve it, the engine is asked
again, and the ladder has already moved up a rung *on its own*: the attempt is
in `contact_events`, which is what `policy.last_rung_used` reads. Nothing here
tells the engine to escalate.

**Stopping** is the part that matters:

| Guard | Why |
|---|---|
| `attempts_exhausted` (default 5) | A borrower who has ignored five contacts about one bounce will not be persuaded by the sixth, and RBI reads a sixth as persistent calling |
| `retry_backoff` (default 12h) | Otherwise a no-answer at 09:00 becomes a second dial at 09:05 |
| `REPEAT_ACTION_DECAY` | A naive EV ranker sends the cheapest channel forever — ₹0.42 always beats ₹7.50 on a small balance. "This precise approach already failed here" has to outweigh its price, or the ladder never climbs |
| case resolution | A payment retires every plan still scheduled for that case. The worst thing a collections system can do is ring somebody about a debt they have already paid |

`GET /treatment/cases` is the ladder view: one row per case, with the rungs
already walked.

## The action space, and the three that reach nobody

`represent_mandate`, `emi_date_change` and `self_service_plan` have
`channel=None`. They consume no contact budget, face no calling-hour veto, and
cost the borrower no goodwill — a debit that lands on payday is something they
never notice.

`NON_CONTACTING` is *derived* from the specs rather than listed, so a new
`channel=None` action cannot be added without inheriting the exemption. That
exemption is why each carries limits of its own in `policy.py`. An action
nothing caps is an action that will be taken until it stops working.

### Why the other two §6 concessions are not actions

The design note proposes `part_payment_offer`, `restructure_offer` and
`self_service_plan`. Only the last is genuinely an action.

A part-payment or a restructure has to be **said to somebody**, which makes it a
property of a contact rather than an alternative to one. Both live on the Action
Contract's `allowedOffers`, where the authority matrix decides them. Modelling
them as actions would have the engine ranking *"send a WhatsApp"* against
*"offer a settlement"* as though those were the same kind of thing — and the
first time the settlement won, a bot would have conceded money no authority
matrix was asked about.

`matrix.decide` escalates restructures and settlements unconditionally, so they
are never reachable from a contract at all. What the contract *does* carry, when
built with a connection, is the late-fee waiver ceiling the matrix already
allows, plus `waiverRequiresIdentityCheck` — because whether the person who
answered is the borrower is not knowable before the call, and a ceiling that
quietly assumed verification would be a bot waiving a fee for whoever picked up
the phone.

| Guard | Why |
|---|---|
| `no_mandate_on_file` / `mandate_not_active` | Retrying does not recreate authority the borrower withdrew |
| `mandate_return_blocks_retry` | A closed account and a cancelled mandate are data and mandate problems; no number of presentations fixes either |
| `mandate_presentation_limit` | The rail's ceiling, expressed as a policy row rather than a constant, because it differs per client |
| `mandate_retry_too_soon` | NACH settles at T+1/T+2; presenting again first debits the borrower twice for one EMI |
| `emi_date_already_aligned` | Self-limiting: a successful change puts the credit ahead of the due date, the gap goes non-positive, and the veto starts firing on its own |
| `arrears_not_yet_worth_a_plan` | One missed EMI is a wobble. Opening a repayment plan for it converts a forgetful borrower into a restructured one |
| `no_digital_surface_to_offer_on` | An offer nobody can see is not an offer — a plan surfaces in the app, the portal or a statement |
| `self_service_plan_already_open` | Two plans on one account is a borrower with two schedules and a dispute about which one they agreed to |

**Return codes are diagnostic, and the engine now reads them.**
`payment_events.reason` has carried the four categories since the schema was
written and nothing branched on them:

| Return | What it is | What happens |
|---|---|---|
| `insufficient_funds` | a **timing** problem | present again, scheduled to the salary credit |
| `mandate_expired` | a **mandate** problem | presentment vetoed; re-registration is the fix |
| `account_closed` | a **data** problem | vetoed; alternate instrument |
| `technical` | not the borrower's problem at all | present at once — **and discretionary contact is suppressed** while the fix is still in our hands |

**Two horizons, and two decay rates.** `TREATMENT_HORIZON_HOURS` is a *contact*
horizon: three days is about how long a decision to dial somebody stays
relevant. Payday comes once a month. Planning a presentment inside 72 hours
excluded the correctly-timed one for roughly nine days in ten, and the urgency
decay — which models *persuasion going stale* — put it below the value floor
even when it fitted. Nobody has to be persuaded of a direct debit, so
non-contacting actions get a longer horizon and a much longer half-life. Both
were found by the corpus simulator, not by reading the code: the action the
design note calls the highest-ROI change in the system was being chosen about
five percent of the time it was eligible, and every veto looked fine.

## Propensity, exploration and the control arm

Three columns on `treatment_decisions`, and none of them can be added later.

**`propensity`** — π(a|x), the probability the logging policy assigned to the
action it took. A deterministic argmax gives every action 1.0, and an
importance-weighted estimate over a log where every weight is 1 is just the
logged average: it cannot say what a *different* policy would have recovered.
You can retrain a model on old data forever; you cannot go back and record the
odds.

**`explore_kind`** — `greedy`, `ranked` or `control_arm`.
`TREATMENT_GREEDINESS` is the dial: 1.0 (the default) is pure argmax and leaves
the engine choosing exactly what it chose before this existed; 0.0 is uniform
over the approved set. In between it is a rank power-normalisation rather than a
softmax over expected value — scores are rupees and rupees are unbounded, so a
temperature tuned on a ₹68 account is degenerate on a ₹6,800 one and the book
would explore only where it has least to learn. Ranks have no scale.

**`policy_version`** — which rule set approved the decision. See below.

### `control` is not the control arm

`control` is the *treated* baseline — whatever the process is already set to.
The untreated arms are `holdout` (decides, enacts nothing) and
**`null_treatment`**, which is the one a live book should use: it withholds
every discretionary action while still permitting a statutory notice. Silence
where the law requires speech is not a control group; it is a compliance breach
that happens to be randomised.

Reaching for `control` when measuring incremental effect contacts every borrower
in it, so the measured uplift is zero by construction and looks like a finding.

## Rules as versioned data

`policy_rules.resolve(conn, tenant_id, at)` answers *as of an instant*. Three
scopes resolve together — statutory, then the tenant's, then the product's — and
a later layer may only ever make a rule **stricter**: the intersection of two
calling windows, the minimum of two caps, the maximum of two cooling-off
periods. Enforced per kind in `_tighten`, not asserted in a comment, because a
client who could widen the statutory window by adding a row would be a client
who could delete the regulation.

With no rows published, `resolve` returns `EMPTY`, every caller falls back to
the constant it used before, and `policy_version` is NULL. That is what makes
the resolver deployable ahead of its data.

`scripts/seed_policy_rules.py` publishes two statutory sets whose windows differ
by effective date, so the same code stamps version 1 on a 2026 decision and 2 on
a 2027 one. Only what genuinely binds from outside is published: the contact
caps and the cooling-off period stay in the environment, because they are
operational settings this platform chose rather than obligations a regulator
imposed — and a published rule is a *ceiling*, so a fabricated statutory cap
would silently clamp every operator who raised theirs.

## The estimators (P1)

Three of the design note's four Layer 1 estimators are learned, and all three
load from one artifact format in `models.py`. The fourth, cost, is accounting.

| Estimator | Replaces | Label |
|---|---|---|
| **reach** | `REACH_PRIOR` | attributed outcome shows contact (`reached`/`ptp`/`refused`) vs `no_answer`/`undeliverable` |
| **timing** | `urgency_halflife_hours` | did the account resolve with *nothing done to it* |
| **uplift** | `p_resolve` | treated arm vs `null_treatment` arm — a T-learner, τ is the difference |

`TREATMENT_SCORER=estimators` wraps `EVScorer` in whatever is loadable. Each
term substitutes independently and falls back independently, so reach and
timing can ship months before τ has a control arm big enough to fit against.
With nothing loadable it *is* `EVScorer`.

Fitted with `scripts/train_treatment_models.py`. Measured on an 18,000-decision
simulated corpus (4,500 accounts, 3,668 in the randomised arm):

| | |
|---|---|
| reach | holdout AUC **0.731** on 5,256 attempts |
| timing | holdout AUC **0.812**, self-cure base rate 0.341 |
| uplift | treated 52.1% vs control 34.1% → **ATE +0.179** |
| ladder | 4 strata had the power to be tested, **1 promoted** |
| off-policy | the estimator challenger scored **−0.019** against the logged policy, on an estimate its own diagnostics call untrustworthy (5,583 of 14,527 decisions unsupported) |

That last row is the system working. The gate refused to promote it, naming
three reasons, and recorded the challenger as considered-and-declined.

### Four things that scored plausible numbers while being wrong

Each was found by a metric that looked like a finding, and each is now a test.

**`paid` is not evidence the phone was answered.** A borrower who was going to
pay anyway pays whether the call connected or not, so counting it as a reach
positive pours the whole self-cure population into the label. Measured: AUC
0.504 with it, 0.70 without.

**The design matrix was unscaled.** `exposure` is thousands of rupees and
`intrusiveness` is 0.15; at a learning rate suiting the second, the first
saturates every sigmoid on the first pass and the model predicts a constant. A
constant predictor scores an AUC of *exactly* 0.500, which reads like "no
signal" rather than "this diverged". The vector stays raw — `4503.96` is
inspectable a year later and `0.31` is not — so the trainer standardises and
folds the scaling back into the coefficients.

**The vector could not tell two borrowers apart.** It carried the account and
the attempt and almost nothing about the person. The design note asks for
segment-level uplift over *bucket × channel × contactability × cash-flow
pattern*; the first three were there. Return-code one-hots, broken promises,
security, disputes and holds are the fourth.

**`wait` decisions carried no feature vector.** Reasonable while silence was
just the absence of an action. Once a control arm existed, a control-arm
decision *is* a wait — so the engine was logging a full vector for every action
it did not take and none for the one it did.

## The granularity ladder (P1.5)

τ is the difference of two noisy quantities, so it needs an order of magnitude
more data than a response model. §9's rule is that granularity is *promoted*,
never chosen: population → segment → individual, and each rung only if the
holdout says the finer model beat the coarser one.

`segments.py` defines what a segment is — **bucket × contactability × cash-flow
pattern**, thirty cells at most, computed from the *logged vector* so an offline
replay and a live decision cannot disagree about which stratum a March decision
belonged to.

Channel is not a dimension, and that is a choice. The design note lists it, but
the action is already a feature *inside* each segment's model (`rung`,
`intrusiveness`, `connect_rate_channel`), so partitioning on it as well would
triple the cell count to learn something the model can already express — and
every cell would hold a third of the data.

### Three gates, all of which must pass

`scripts/train_treatment_models.py` fits a T-learner per stratum and keeps only
what survives:

| Gate | Test | Why |
|---|---|---|
| **Power** | ≥150 treated and ≥200 control rows | a difference of two rates below that is mostly the arm split |
| **Heterogeneity** | segment ATE more than 1.96 SE from the population ATE | the causal gate, backed by the randomisation rather than by a fit |
| **Holdout fit** | both halves beat the population halves in log loss on held-out rows | the finer model has to actually predict better |

The middle gate is the load-bearing one. A segment model will nearly always fit
its own stratum better than a pooled model does — fewer rows to explain and its
own intercept — so fit quality alone would promote every stratum, which is
overfitting, and on a difference of two noisy quantities it is exactly how
confident noise gets shipped.

The report is emitted whether or not anything is promoted. *"We tested nine
strata and two beat the population"* is the finding; an artifact that silently
contained two segments would tell you only half of it.

### Shrinkage, not switching

A promoted segment never answers alone. `SegmentModel.weight(k) = n / (n + k)`
blends it toward the population estimate, so a stratum with 600 rows barely
moves the pooled answer and one with 60,000 dominates it — continuously.

Hard-switching at a threshold would make τ discontinuous across a boundary a
borrower crosses by *aging one day*. It is also precisely the machinery §14
needs for cross-tenant priors: the only thing that changes there is what "the
pool" means.

A segment fitted under a different `SEGMENT_VERSION` is ignored wholesale — the
keys would parse and score, they would just mean a different population, which
no shape check can detect. A *malformed* segment is dropped while the artifact
still loads, because the population model is right behind it; a malformed
population model is refused, because nothing is.

## Drift, calibration and the promotion gate (§15)

`monitor.py` runs three checks that fail in three different ways, which is why
there is no single "model health" score:

- **Feature drift** — recent logged vectors against the artifact's training
  means, in units of the training σ. *"dpd has moved by 11"* is not a finding
  until you know whether 11 is a tenth of a σ or three. An artifact with no
  recorded `stdevs` reports that it cannot be measured rather than reporting no
  drift, which is what inventing a scale from the recent data would do.
- **Reach calibration** — reliability bins and ECE against the `pReach` the
  engine logged. That number is what the EV formula multiplied by rupees, so its
  honesty is the thing that matters; re-predicting with today's model would
  score today's model on yesterday's decisions and call the difference
  calibration.
- **Uplift calibration** — predicted mean τ against the ATE the randomised arm
  measured. τ has no per-row label, so there is no curve to draw; but there is
  one number the randomisation gives for free. **A model claiming +18 points on
  a book whose control arm measured +4 has not found uplift — it has found
  self-curers.** This is the only check that sees it.

`registry.py` is the champion/challenger ledger. Promotion is **refused by
default**: every rule is a reason to say no and there is no positive rule, because
the cost of not promoting a good model is some foregone lift and the cost of
promoting a bad one is a book's worth of decisions made confidently wrong.

    scripts/promote_model.py --target uplift --artifact <path> --check
    scripts/promote_model.py --target uplift --artifact <path> \
        --evaluation report.json --by <who> --reason "SNIPS +0.031, ESS 62%"
    scripts/promote_model.py --verify

Refusals: no evaluation attached; holdout lift below `MIN_HOLDOUT_LIFT`; the
estimate reporting itself untrustworthy; an uplift model naming no control arm;
a measured ATE at or below zero; a simulated corpus; a stale artifact.

**The registry gates and records. It does not serve.** `models.load_*` stays a
pure file read — it runs in a service on the audio path of a live call, and a
database between a scorer and its coefficients trades a real availability
guarantee for a bookkeeping one. Promotion is what copies the artifact into the
serving path, and `artifact_sha` is what makes that checkable: `--verify`
detects a file replaced *after* a promotion, which a registry of version strings
alone could not see. One champion per target is enforced by a partial unique
index, so demotion is not something the promotion code has to remember.

## The scoreboard (§17)

`GET /treatment/metrics` — six categories, and the headline is **incremental
recovery per rupee against the control arm, never a collections rate**. A
response model looks excellent on collections rate precisely because it targets
borrowers who were going to pay anyway and books their payments as its own, so a
dashboard headlined that way shows the wrong system winning, in green, for
months.

Where an arm is too thin to support a causal figure the field says so and
returns nothing. A metric that silently degrades to a non-causal proxy is worse
than a missing one: a missing metric gets chased, a green one gets cited.

Three honesty notes worth reading before the numbers:

- **Recovery is read from `ledger_entries`, not `payment_events`.** The name
  misleads: `payment_events.kind` is CHECK-constrained to `'bounce'`, so it is a
  *returns* ledger and a recovery figure read from it is structurally zero.
  Found by this metric reporting nothing recovered on a corpus where a fifth of
  the book had cured — caught only because the corpus was large enough for zero
  to be obviously wrong, which is the same class of failure as the complaint
  rate below and the reason both are called out here rather than left to be
  rediscovered.
- **Attributable recovery is the incremental share only.** The rest belonged to
  borrowers the control arm says would have paid anyway. Crediting all of it is
  the response-model error in accounting form.
- **The complaint rate has no source and says so.** `disputes.type` is
  constrained to billing disputes — `paid_already`, `wrong_amount`,
  `not_my_account`, `fee_waiver`, `duplicate_charge`, `fraud` — with no conduct
  or harassment value, and nothing else in the schema records a complaint about
  *how* a borrower was contacted. It needs a complaint intake before it can be a
  number.

**Window and cap breaches are audited from the ledger, not read off a denial
reason.** There is no reason code for a breach and there should not be: the gate
does not record permission it did not grant. So the check runs after the fact
over allowed outbound contacts, and anything it finds got around
`contact_policy.evaluate()` entirely — which means an executor reached a
borrower without asking, and no amount of correct gate logic would have caught
it. Target is zero, not "low".

**Voice minutes per lakh recovered** is deliberately prominent. §18's point is
that a working decision engine's first observable effect is a drop in call
volume, and that this is the intended behaviour. Putting the drop next to the
recovery it did not cost is what turns an alarming chart into the value
proposition.

## Sizing the control arm (§19.2)

    scripts/power_control_arm.py --book 50000 --delinquency 0.05 --mde 0.02

Prints the trade-off curve rather than a recommendation: for each control-arm
fraction, the cases needed, the weeks to get them, and the incremental recovery
forgone by withholding treatment from that arm. Choosing a point on it means
weighing a measurement against real borrowers who were not contacted, and that
is a decision with a name attached to it, not an argmax.

Two things it gets right that a naive version would not:

- **n is cases, not decisions.** `config.assign_variant` hashes the *customer
  id*, so the unit of randomisation is the borrower. Counting decisions would
  count one borrower's fortnight of daily sweeps as fourteen independent
  observations of the same coin and report a book as powered weeks before it is.
- **Repeat borrowers are clustered.** `--design-effect` applies the standard
  `1 + (m−1)·ICC` inflation; `--from-db` measures the clustering rather than
  assuming it away.

The finding on a 50k book at 5% delinquency: a **5-point** effect is detectable
in 5–15 weeks depending on the split. A **2-point** effect — which is the size
uplift work actually deals in — is **not powerable inside two quarters at any
split**. That is the product-strategy answer §19.2 asks for, and it is better
known now than after a contract is shaped the other way.

## Delivery receipts

`contact_delivery_events` is an append-only log of transitions, not a status
column. WhatsApp receipts already arrived and already updated
`messages.delivery_status`, but that is a *current state*: a message that went
sent → delivered → read leaves only "read", and the moment it was read — the
fact that separates a borrower reachable at 09:00 from one reachable at all —
was overwritten. SMS had no receipts at all; the Twilio SID was logged and
dropped.

`features._reachability` now prefers real receipts over the inbound-reply
proxy, and takes `responsive_hours` from read times as well as voice connects.
A borrower who reads every message and answers none is perfectly reachable and
completely invisible to a reply rate.

## Off-policy evaluation

`ope.py` answers what a *different* policy would have recovered, from the log
alone. `scripts/evaluate_policy.py` is the champion/challenger gate.

Two questions, deliberately different machinery:

- **"Does contacting people work?"** — a difference of means between the treated
  arms and `null_treatment`. The arm assignment *is* the randomisation, so no
  reweighting is applied; adding importance weights would add variance to a
  question already settled by design.
- **"Would a different ranking have done better?"** — IPS / SNIPS / DR over the
  treated arms only. The control arm is excluded: it is not a different ranking
  of the same actions, it is the absence of one.

**Read the diagnostics before the estimate.** ESS, unsupported count and
clipping are reported with every number, and `Estimate.trustworthy` is what
gates a promotion. A deterministic logging policy has support on exactly one
action per decision, so *every* disagreement is unsupported — which is why
exploration had to come first.

Measured on a 400-account, 10-day simulated book: the greedy-on-logged-EV policy
scores SNIPS 0.594 against a logged baseline of 0.540, ESS 64%, 0 unsupported —
trustworthy. The estimator-backed challenger scores −0.076 with ESS 26.6% and
1054 of 2960 decisions unsupported, and is flagged **do not act on this**. That
is the machinery working: it refuses to endorse a policy it cannot evaluate.

## Layer 3 — book allocation

`allocate.py`. Not an LP — two million accounts by nine actions is eighteen
million variables. Lagrangian decomposition instead: price each scarce resource,
subtract price × usage from every action's value, and the problem falls back
into independent per-account argmaxes. Solve for the price at which demand meets
capacity and the local answers are jointly optimal.

**The dual prices are the output that matters**, not the plan. `costs.for_action`
adds today's price to the ledger cost, so:

```
agent capacity abundant   ->  contact stays cheap
agent capacity scarce     ->  contact becomes expensive
field capacity exhausted  ->  field falls below the floor by itself
```

Nobody writes down "stop making field visits below ₹900". On a 200-account book
with 400 agent-minutes, the solver prices an agent-minute at ₹17.50, field
visits collapse from 272 to zero, and `represent_mandate` absorbs the displaced
demand. It also found that the binding constraint was agent *minutes* rather
than field slots — 45 minutes a visit is what actually runs out.

`TREATMENT_DUAL_PRICING` is off by default and the write is a separate switch
from the read, on purpose: an optimiser amplifies estimator error rather than
correcting it, so solve first, look at the numbers, then decide.

## The corpus

**`agent_core/treatment/sweep.py`** — one decision per delinquent account per
local day, `SKIP LOCKED`, resumable from a cursor. Off unless
`TREATMENT_SWEEP=1`. Until it existed the engine only woke on a bounce or a
broken promise, so an account rolling silently 30 → 60 → 90 never got a
decision at all — which is why the log held four rows.

**`scripts/simulate_treatment_corpus.py`** — a synthetic delinquent book, run
through the real engine, tagged `mode='simulated'`. Gated on
`TREATMENT_SIMULATION_OK=1`. The executor, the follow-through loop and the
trainers all exclude it with one predicate, and that predicate is the entire
safety story: the simulator writes decisions that look exactly like live ones,
because that is the point of it.

Its latent truth encodes a real self-cure process and heterogeneous uplift that
varies *inversely* with it — the borrowers most likely to pay anyway are the
ones our contact changes least. Without that inversion there is nothing for an
uplift model to find that a response model would not find first.

## The vetoes

Delegated where a definition already exists, and never duplicated:

| Rule | Where it lives |
|---|---|
| RBI 08:00–19:00, DND, opt-out, daily/weekly cap, cooling-off, consent window | `contact_policy.evaluate()` — P6, one definition shared with the dialler, the WhatsApp drain, the PTP confirm and the document desk |
| Hardship, dispute, complaint, bereavement, legal | `treatment_holds` (new) |
| Which actions a DPD bucket permits at all | `actions.BUCKETS` |
| One rung of escalation per decision | `policy.veto` against enacted history |
| Field only after digital exhaustion, only if proportionate | `policy._field_veto` |
| Statutory notice only when the clock is real | `policy._legal_veto` |
| Third-party / reference contact | `policy.permits_third_party_contact` — always `False`; there is no table in this schema in which such a consent could be recorded, and the gate exists to be the one place that changes when there is |
| Collection vs upsell separation | `policy.suppresses_upsell`, read by `reco.arbitration` |

A hold is a **row**, which is the point. Hardship used to be a routing rule that
fired only if a human was already on the call; as a row, a bot at 02:00 is bound
by it exactly as a supervisor is.

## Modes

| `TREATMENT_MODE` | Behaviour |
|---|---|
| `off` | never decides; callers get `engine_off` |
| `shadow` | **default.** Decides and logs everything, enacts nothing |
| `live` | decides, logs, and the executor acts |

An unrecognised value degrades to `shadow`, not `off` — a typo must not silently
stop collecting the data the rollout decision depends on.

One deliberate divergence from reco: **shadow still returns the plan**. Reco
hides its shadow output because *speaking* is the risk it manages. Here the risk
is *contacting*, and showing a supervisor exactly what the engine would have
done — while doing none of it — is the entire point of the shadow fortnight.
`suppressed` is still true and `enact` still refuses.

## Rollout

1. **Shadow (2 weeks).** `GET /treatment/insights` gives coverage, the
   suppression breakdown, the action mix and p50 latency. The exit question is
   not "is the ranking good" but "does the ladder generate field visits and
   agent hours the floor can absorb".
2. **Live, digital only.** Set `TREATMENT_MODE=live` with
   `TREATMENT_MIN_EV` raised so only WhatsApp/SMS clears. Watch complaint rate,
   contact-policy denial rate and PTP keep-rate.
3. **Live, full ladder.** Lower the floor. `field_visit` and `legal_notice`
   still have no executor — that is P8 and P9 — so they are recorded as
   `cancelled` with the executor named rather than retrying forever.
4. **Learn.** Once the log holds enough labelled outcomes, train a propensity
   model on the logged vectors and register it behind `TREATMENT_SCORER` with
   automatic fallback to `EVScorer`.

Step 0 comes before all of them and is new: turn on `TREATMENT_SWEEP` and set
`TREATMENT_GREEDINESS` below 1.0 with a `null_treatment` arm in
`TREATMENT_AB_SPLIT`. Nothing downstream — uplift, off-policy evaluation, a
control arm that means anything — exists without a corpus, and the corpus is
the one thing that cannot be backfilled.

## Configuration

Read from the environment at call time, so a change takes effect without a
restart.

| Variable | Default | Meaning |
|---|---|---|
| `TREATMENT_MODE` | `shadow` | `off` \| `shadow` \| `live` |
| `TREATMENT_SCORER` | `ev` | which `Recommender` |
| `TREATMENT_MIN_EV` | `2.0` | rupees below which we would rather wait |
| `TREATMENT_RECOVERY_FRACTION` | `0.35` | fraction of exposure a cure recovers |
| `TREATMENT_URGENCY_HALFLIFE_HOURS` | `36` | hours over which waiting halves the value |
| `TREATMENT_FATIGUE_COST` | `6.0` | ₹ of goodwill per unit intrusiveness per touch spent today |
| `TREATMENT_MAX_RUNG_ADVANCE` | `1` | ladder steps per decision |
| `TREATMENT_RESERVE_BUDGET` | `true` | hold the day's last slot for something better |
| `TREATMENT_RESERVE_MARGIN` | `3.0` | multiple of the floor that justifies spending it |
| `TREATMENT_FIELD_DIGITAL_EXHAUSTION` | `4` | unanswered digital sends before a visit is offerable |
| `TREATMENT_HORIZON_HOURS` | `72` | planning horizon |
| `TREATMENT_MAX_ATTEMPTS_PER_CASE` | `5` | attempts before the ladder stops |
| `TREATMENT_RETRY_BACKOFF_HOURS` | `12` | minimum gap before re-deciding a case |
| `TREATMENT_GRACE_*_HOURS` | see `config.py` | how long an attempt has before it counts as unanswered |
| `TREATMENT_COST_*` | see `config.py` | ₹ per attempt, all-in |
| `TREATMENT_LLM_RERANK` | `false` | let a model reorder the approved list |
| `TREATMENT_AB_SPLIT` | — | `control:80,null_treatment:20` |
| `TREATMENT_VARIANTS` | — | JSON, extends the built-ins |
| `TREATMENT_GREEDINESS` | `1.0` | 1.0 argmax, 0.0 uniform over the approved set |
| `TREATMENT_SWEEP` | `false` | run the delinquent-book sweep |
| `TREATMENT_MANDATE_EXECUTOR` | `lms` | `rail` (we present) or `lms` (we recommend) |
| `TREATMENT_MANDATE_RAIL_MODULE` | — | adapter exposing `present(...)`, required by `rail` |
| `TREATMENT_MANDATE_MAX_PRESENTATIONS` | `3` | fallback when no policy rule is published |
| `TREATMENT_COST_REPRESENT_MANDATE` | `0.50` | not zero on purpose — see `config.py` |
| `TREATMENT_COST_EMI_DATE_CHANGE` | `15.0` | an LMS work item and somebody's ten minutes |
| `TREATMENT_COST_SELF_SERVICE_PLAN` | `8.0` | no schedule to rebuild — the cost is the servicing tail of a half-completed plan |
| `TREATMENT_SCORER` | `ev` | `estimators` to use whatever models load |
| `TREATMENT_REACH_MODEL_PATH` | `models/treatment_reach.json` | |
| `TREATMENT_TIMING_MODEL_PATH` | `models/treatment_timing.json` | |
| `TREATMENT_UPLIFT_MODEL_PATH` | `models/treatment_uplift.json` | |
| `TREATMENT_MODEL_MAX_AGE_DAYS` | `90` | refuse an artifact older than this |
| `TREATMENT_ALLOW_SIMULATED_MODELS` | `false` | let a model of a synthetic book score real borrowers |
| `TREATMENT_DUAL_PRICING` | `false` | let capacity prices reach `costs.for_action` |
| `TREATMENT_CAPACITY_AGENT_MINUTES` | — | unset means unconstrained, not zero |
| `TREATMENT_CAPACITY_FIELD_SLOTS` | — | |
| `TREATMENT_CAPACITY_BOT_MINUTES` | — | |
| `TREATMENT_CAPACITY_MANDATE_PRESENTATIONS` | — | |

Built-in arms: `control`, `eager`, `patient`, `holdout`. Bucketing is hashed on
the **customer**, so a borrower treated patiently after Monday's bounce and
eagerly after Thursday's cannot happen.

## Extending

**A different data source** — implement `FeatureProvider.build()` against your
schema. Nothing downstream changes; everything depends on `AccountFeatures` and
`Trigger`, never on a table name.

**A different ranker** — implement `Recommender` (`name`, `version`, `score()`)
and register it in `scoring.build_scorer`. A scorer cannot add an action, cannot
overturn a veto, and cannot reach the database. That is what makes swapping one
safe.

**An LLM** belongs in `rerank.py` and only there. It may reorder an approved
list and write one sentence; it may not introduce an action, change a channel or
an instant, or put a figure on screen that nothing computed — the rationale is
rejected outright if it contains a number absent from the payload it was given.
Borrower speech reaches that context through the account summary, so the guard
is enforced in code rather than requested in the prompt.

## Guarantees worth not breaking

- `recommend_treatment()` never raises, and never opens its own connection when
  given one. It is called from inside bounce ingest, which holds `FOR UPDATE` on
  the account row while it asks what to do next.
- A scorer never sees a vetoed action.
- `wait` is always in the candidate set, so there is no state with no legal
  action.
- Unknown facts are **absent, not zero**. A borrower we have never dialled gets
  the channel prior and a decision log that says so.
- Every invocation is logged, including suppressed and shadow ones. Those are
  the counterfactuals; without them there is no offline evaluation and no
  answer to "why did the engine go quiet on Tuesday?".
- The contact gate runs **again** at send time. A plan made at 09:00 for 19:30
  was made against a budget that has since been spent and a consent that may
  have been withdrawn.
- The ladder **runs out**. A loop that never stops is not a collections ladder,
  it is persistent calling with extra steps.
- A shadow decision is never labelled `no_answer`. Nothing was sent, so there is
  nothing to call unanswered, and labelling it would manufacture a training
  signal out of a decision nobody acted on.
