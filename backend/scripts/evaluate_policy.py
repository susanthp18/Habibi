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
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import config, models, ope  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("evaluate_policy")


def _row(label: str, est: ope.Estimate) -> str:
    flag = "" if est.trustworthy else "  <- do not act on this"
    return (
        f"{label:<28} {est.value:>7.4f}  ±{est.stderr:<7.4f}"
        f" lift {est.lift:>+7.4f}"
        f"  n={est.n:<6} ess={est.ess:>7.1f} ({est.ess_fraction:>5.1%})"
        f" unsup={est.unsupported:<5}{flag}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit machine-readable output")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    modes = ("shadow", "live") + (("simulated",) if args.include_simulated else ())

    with db.engine.connect() as conn:
        # Out of the API's fifteen-second budget: this reads the whole corpus,
        # and it is a batch job rather than a request.
        conn.execute(text("SET statement_timeout = 0"))
        effect = ope.treatment_effect(conn, modes=modes)
        obs = ope.observations(conn, modes=modes, limit=args.limit)

    if not obs:
        logger.error(
            "no evaluable decisions. A decision is evaluable once it has an "
            "outcome and a logged propensity — if the corpus is large and this "
            "is empty, the engine is still logging deterministic argmax "
            "decisions and TREATMENT_GREEDINESS needs lowering."
        )
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
    report: dict[str, Any] = {"treatmentEffect": effect.to_log(), "policies": {}}

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
        snips = dict(report["policies"][best]["snips"])
        snips["policy"] = best
        snips["ate"] = effect.ate
        snips["ateSignificant"] = effect.significant
        report["promotion"] = snips

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
