#!/usr/bin/env python
"""Score candidate policies against the logged corpus, without touching a borrower.

    .venv/Scripts/python scripts/evaluate_policy.py
    .venv/Scripts/python scripts/evaluate_policy.py --include-simulated
    .venv/Scripts/python scripts/evaluate_policy.py --json

The champion/challenger gate. A challenger is promoted on holdout lift, never on
offline metrics alone — and this is the offline half: it says whether a
challenger is worth the holdout at all, which is the expensive part.

Two questions, answered with different machinery on purpose:

**"Does contacting people work?"** is the treatment effect, and it is a
difference of means between the treated arms and the randomised control arm.
The arm assignment *is* the randomisation, so no reweighting is applied. Adding
importance weights here would add variance to answer a question already settled
by design.

**"Would a different ranking have done better?"** is off-policy evaluation, and
it is IPS / SNIPS / doubly-robust over the treated arms only. The control arm is
excluded because it is not a different ranking of the same actions — it is the
absence of one.

**Read the diagnostics before the estimate.** An off-policy number without its
effective sample size and unsupported count is worse than no number, because it
is a number. Ten thousand rows with an ESS of forty is an estimate computed from
forty rows wearing ten thousand rows' confidence interval, and a deterministic
logging policy makes *every* disagreement unsupported — which is exactly why
exploration had to come first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import (  # noqa: E402
    config,
    evaluation_seal,
    models,
    ope,
    registry,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("evaluate_policy")


def _row(label: str, est: ope.Estimate) -> str:
    flag = "" if est.trustworthy else "  <- do not act on this"
    return (
        f"{label:<28} {est.value:>7.4f}  ±{est.stderr:<7.4f}"
        f" lift {est.lift:>+7.4f}"
        f"  n={est.n:<6} ess_rows={est.ess:>7.1f}"
        f" ess_cust={est.ess_customers:>6.2f}/{est.clusters:<4} ({est.ess_fraction:>5.1%})"
        f" lev={est.max_customer_share:>5.1%} unsup={est.unsupported:<5}{flag}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--pre-registration",
        default=None,
        help=(
            "the pre-registration this evaluation runs under (§8.12 gate 14). "
            "File one with scripts/pre_register.py BEFORE running this — the "
            "gate compares its filed_at against the computed_at stamped into "
            "the sealed block below, so a pre-registration filed afterwards "
            "is refused rather than accepted."
        ),
    )
    ap.add_argument(
        "--contract-min",
        type=int,
        default=ope.MIN_LOGGING_CONTRACT,
        help=(
            "logging-contract floor. Defaults to what the schema has required "
            "since W2. Pass 1 to see what the pre-cutover fused-propensity "
            "rows would have said, and read the answer as a diagnostic."
        ),
    )
    ap.add_argument(
        "--artifact",
        default=None,
        help=(
            "the challenger this evaluation is about. Its sha256 is written "
            "into the promotion block and the promotion gate recomputes it, so "
            "an evaluation can no longer describe one artifact and promote "
            "another. Without it the block is still emitted and promote_model "
            "will refuse it, which is the correct outcome rather than a "
            "silently weaker one."
        ),
    )
    args = ap.parse_args()

    modes = ("shadow", "live") + (("simulated",) if args.include_simulated else ())

    tenant = db.current_tenant()

    with db.engine.connect() as conn:
        # Out of the API's fifteen-second budget: this reads the whole corpus,
        # and it is a batch job rather than a request.
        conn.execute(text("SET statement_timeout = 0"))
        effect = ope.treatment_effect(conn, modes=modes)
        corpus = ope.scan(
            conn, modes=modes, limit=args.limit, contract_min=args.contract_min
        )
        margin, margin_basis = registry.value_margin(conn, tenant_id=tenant)
    obs = corpus.observations

    if not obs:
        # Not "no evaluable decisions". §8.12 makes an unevaluable gate a
        # refusal, and a refusal that does not name its number sent the last
        # reader of this message to lower TREATMENT_GREEDINESS on a corpus where
        # exploration was already running at δ = 0.10.
        for reason in corpus.scope.objections:
            logger.error("%s", reason)
        return 1

    # Whatever is fitted right now. Loading them here rather than inside the
    # policy keeps the artifacts' provenance visible in the report: a challenger
    # built on a model of a synthetic book should say so on the same screen as
    # its lift.
    reach, timing, uplift = models.load_reach(), models.load_timing(), models.load_uplift()

    policies: list[tuple[str, ope.Policy]] = [
        ("greedy on logged EV", ope.greedy_on_logged_ev),
    ]
    if reach or timing or uplift:
        fitted = "+".join(
            n for n, a in (("reach", reach), ("timing", timing), ("uplift", uplift)) if a
        )
        policies.append(
            (
                f"estimators ({fitted})",
                ope.estimator_policy(
                    reach=reach,
                    timing=timing,
                    uplift=uplift,
                    recovery_fraction=config.policy().recovery_fraction,
                ),
            )
        )
    else:
        logger.info(
            "no fitted estimators found — comparing the logged policy against its "
            "own greedy form only. Run scripts/train_treatment_models.py first."
        )

    reward_model = ope.logged_ev_reward()
    report: dict[str, Any] = {
        "treatmentEffect": effect.to_log(),
        "corpus": corpus.scope.to_log(),
        "valueMargin": {"margin": margin, "basis": margin_basis},
        "policies": {},
        "delta": {},
    }
    if not args.json:
        scope = corpus.scope
        print(
            f"\nCorpus: {scope.evaluable} evaluable of {scope.considered} considered"
            f"  (suppressed kept: {scope.suppressed_included})"
        )
        for reason, count in sorted(scope.excluded.items(), key=lambda kv: -kv[1]):
            print(f"  excluded {count:>6}  {reason}")
        print(
            "  gate 7 margin: "
            + (f"{margin:+.4f}  ({margin_basis})" if margin is not None else f"unmeasurable — {margin_basis}")
        )

    for label, policy in policies:
        estimates = {
            "ips": ope.ips(obs, policy),
            "snips": ope.snips(obs, policy),
            "dr": ope.doubly_robust(obs, policy, reward_model),
        }
        report["policies"][label] = {k: v.to_log() for k, v in estimates.items()}
        if not args.json:
            print(f"\n{label}")
            for est in estimates.values():
                print("  " + _row(est.method, est))

    # A promotion-ready block, so the output of this script is the input to
    # promote_model.py without anybody reshaping JSON by hand at the moment they
    # are trying to ship. SNIPS is the method: bounded variance, slightly
    # biased, which is the right trade for a gate -- IPS is unbiased and can
    # return an estimate three times the logged mean off four heavy weights.
    #
    # The measured ATE rides along because the uplift gate needs it and it comes
    # from the randomisation rather than from any policy comparison.
    challengers = [k for k in report["policies"] if k != "greedy on logged EV"]
    if challengers:
        best = max(
            challengers,
            key=lambda k: report["policies"][k]["snips"]["lift"],
        )
        # Δ-OPE against the champion, which here is the engine's own greedy form
        # — the policy that would serve with exploration switched off. The
        # difference is estimated directly rather than by differencing two
        # estimates, and the interval that gates is restricted to the rows where
        # the two actually disagree (§8.9 tier 1).
        difference = ope.delta(
            obs,
            ope.greedy_on_logged_ev,
            dict(policies)[best],
            reward_model=reward_model,
        )
        report["delta"][best] = difference.to_log()
        if not args.json:
            d = difference
            print(f"\nΔ-OPE  {best}  vs  greedy on logged EV")
            print(
                f"  Δ per decision {d.value:+.4f}   on the disagreement set "
                f"{d.disagreement_value:+.4f}"
            )
            print(
                f"  disagreement {d.disagreement_n}/{d.n} ({d.disagreement_fraction:.1%})"
                f" over {d.disagreement_clusters} borrowers"
                f"   ess {d.ess_customers:.2f}   leverage {d.max_customer_share:.1%}"
            )
            print(
                f"  interval [{d.interval.low:+.4f}, {d.interval.high:+.4f}]"
                f" ({d.interval.method}, {d.interval.clusters} clusters)"
            )
            print(
                f"  EV_lcb {d.lcb.lower:+.4f} (α={d.lcb.alpha})"
                f"   LS corroboration {d.ls.lower:+.4f}"
            )
            for reason in d.objections:
                print(f"  CANNOT BE EVALUATED: {reason}")

        snips = dict(report["policies"][best]["snips"])
        snips["policy"] = best
        snips["ate"] = effect.ate
        snips["ateSignificant"] = effect.significant
        # §8.12 gate 7 promotes on the bound. It travels beside the point
        # estimate rather than instead of it, because a validator reading a
        # refusal wants to see how far the bound fell short of the number.
        snips["lcb"] = difference.lcb.lower if math.isfinite(difference.lcb.lower) else None
        snips["delta"] = difference.to_log()
        snips["objections"] = difference.objections
        snips["corpus"] = corpus.scope.to_log()
        # Gate 14. `computed_at` sits inside the body the seal covers, so it
        # cannot be moved to predate a pre-registration without invalidating the
        # seal — which is why the two gates are one mechanism read twice.
        snips["computed_at"] = datetime.now(timezone.utc).isoformat()
        if args.pre_registration:
            snips["pre_registration_id"] = args.pre_registration
        # Gate 2. The sha binds the numbers above to one file, and the seal
        # says they were produced by something holding the key rather than
        # edited on the way to the gate.
        if args.artifact:
            snips["artifact_sha"] = hashlib.sha256(
                Path(args.artifact).read_bytes()
            ).hexdigest()
        report["promotion"] = evaluation_seal.sealed(snips)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("\nTreatment effect (difference of means against the randomised arm)")
    print(
        f"  treated {effect.treated_rate:.1%} on {effect.treated_n} decisions"
        f"   control {effect.control_rate:.1%} on {effect.control_n}"
    )
    print(
        f"  ATE {effect.ate:+.4f} ± {effect.stderr:.4f}"
        f"   {'clear of zero' if effect.significant else 'NOT clear of zero'}"
    )
    if effect.control_n == 0:
        print(
            "\n  No control arm in this corpus. Every number above is a response"
            "\n  rate, not a treatment effect — set TREATMENT_AB_SPLIT."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
