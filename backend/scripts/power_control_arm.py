#!/usr/bin/env python
"""Can this book power a control arm at all? — §19.2, answered with a number.

    .venv/Scripts/python scripts/power_control_arm.py
    .venv/Scripts/python scripts/power_control_arm.py --book 50000 --delinquency 0.05
    .venv/Scripts/python scripts/power_control_arm.py --from-db --include-simulated
    .venv/Scripts/python scripts/power_control_arm.py --mde 0.03 --json

The design note calls this a question requiring a human decision, and it is —
but the human should be given an arithmetic answer to decide against, because
the failure mode here is not choosing wrong. It is running a control arm for six
months, withholding treatment from thousands of borrowers, and discovering that
the book could never have detected the effect being looked for. The borrowers
paid for that experiment either way.

**The quantity is the sample size for a difference of two proportions.** Cure
rate in the treated arm versus cure rate in the randomised control arm, at the
smallest effect worth acting on::

    n_control = (z(1-α/2) + z(power))² · [p_c(1-p_c) + p_t(1-p_t)/r] / δ²

with ``r`` the treated-to-control ratio, so an 80/20 split needs a larger total
than a 50/50 one to reach the same power. That asymmetry is the whole decision:
a 50/50 split answers fastest and withholds the most treatment.

**n is cases, not decisions, and the difference is an order of magnitude.**
``config.assign_variant`` hashes the *customer id*, so the unit of randomisation
is the borrower and every decision on them lands in the same arm. Counting
decisions would count one borrower's fortnight of daily sweeps as fourteen
independent observations of the same coin, and report a book as powered weeks
before it is. The observational unit is therefore the delinquency case — the
same case model ``followthrough.py`` already attributes outcomes to — which
accrues at roughly the rate accounts enter delinquency, not the rate the sweep
runs.

**Repeat borrowers are correlated, and that is priced too.** A customer who goes
delinquent three times contributes three cases to the same arm, which are not
three independent draws. ``--design-effect`` inflates the requirement by the
standard ``1 + (m−1)·ICC``; the default assumes one case per customer in the
window, which is the optimistic end and is labelled as such.

**The control arm is not free, and this prices it.** Every account in the arm is
an account whose discretionary outreach was withheld, so its cost is the
foregone incremental recovery — exposure × recovery fraction × δ, summed over
the arm. Reported alongside the weeks, because "twelve weeks at 20%" and
"five weeks at 50%" are not comparable until both carry their price.

**What this deliberately does not do** is recommend a split. It prints the
trade-off curve. Choosing a point on it means weighing a measurement against
foregone recovery on real borrowers, and that is a decision with a name
attached to it, not an argmax.

The default numbers are planning figures and are labelled as such. Run
``--from-db`` once the shadow corpus has a fortnight in it and the observed
control-arm cure rate replaces the guess.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from statistics import NormalDist
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("power_control_arm")

# The report is denominated in rupees and a Windows console defaults to cp1252,
# which cannot encode ₹ and raises rather than degrading. A report that dies on
# its own currency symbol is not a report.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
        pass

#: Control-arm fractions worth showing. Below 10% the arm is so thin that the
#: total book required explodes; above 50% the arm is the majority of the book
#: and it stops being an experiment and starts being a decision not to collect.
FRACTIONS: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.33, 0.50)

#: Planning defaults, all of them guesses and none of them measured here.
#: The self-cure figure especially: §2 is explicit that no external number
#: describes it, because published "early-stage recovery" rates describe
#: recovery achieved *through* collections effort, which is the opposite of
#: self-cure. This is a starting point for the arithmetic, not a claim.
DEFAULT_CONTROL_CURE = 0.45
DEFAULT_MDE = 0.05
DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.80

#: Weeks a delinquency case stays open before it cures, rolls or is written to
#: an outcome. Sets how fast cases accrue from a book of a given size: a book
#: holding N delinquent accounts yields roughly N / this many new cases a week.
#: Four and a third weeks is one EMI cycle, which is the natural clock here —
#: a case is opened by a missed instalment and closed by the next one.
DEFAULT_CASE_WEEKS = 4.33


def sample_size(
    *,
    p_control: float,
    mde: float,
    ratio: float,
    alpha: float,
    power: float,
    design_effect: float = 1.0,
) -> tuple[int, int]:
    """(control, treated) accounts needed to detect ``mde`` at ``power``.

    Two-sided, unpooled variance. Unpooled rather than pooled because the two
    arms are not assumed to share a rate — that assumption is the null being
    tested, and using it to size the test makes the test slightly optimistic
    about its own power.
    """
    p_treated = min(0.999, max(0.001, p_control + mde))
    z_alpha = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    z_power = NormalDist().inv_cdf(power)
    variance = p_control * (1 - p_control) + p_treated * (1 - p_treated) / max(0.01, ratio)
    n_control = ((z_alpha + z_power) ** 2) * variance / (mde**2)
    # Cases from one borrower are not independent draws. The design effect is
    # the standard inflation for clustered sampling, and leaving it at 1.0 is a
    # claim that no borrower in the window goes delinquent twice.
    n_control *= max(1.0, design_effect)
    n_control = int(-(-n_control // 1))  # ceil without importing math
    return n_control, int(-(-(n_control * ratio) // 1))


def observed(include_simulated: bool) -> dict[str, Any] | None:
    """Measured inputs from the decision log, where there are any.

    Returns None rather than defaults when the corpus is too thin to say
    anything, so the report can print "measured" or "assumed" honestly instead
    of dressing a planning figure as an observation.
    """
    import db
    from sqlalchemy import text

    modes = ["shadow", "live"] + (["simulated"] if include_simulated else [])
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE variant = 'null_treatment')::int AS control_n,
                  count(*) FILTER (
                    WHERE variant = 'null_treatment' AND outcome IN ('paid','ptp')
                  )::int AS control_cured,
                  count(*) FILTER (
                    WHERE variant = 'null_treatment' AND outcome IS NOT NULL
                  )::int AS control_labelled,
                  count(*)::int AS decisions,
                  -- Cases, not decisions. A case is one delinquency episode
                  -- (customer x trigger kind x trigger ref), which is the unit
                  -- followthrough.py attributes an outcome to and therefore the
                  -- unit that can be counted once.
                  count(DISTINCT (customer_id, trigger_kind, trigger_ref))::int AS cases,
                  count(DISTINCT customer_id)::int AS customers,
                  EXTRACT(EPOCH FROM (max(created_at) - min(created_at)))
                    / 604800.0 AS weeks,
                  COALESCE(avg(expected_value) FILTER (
                    WHERE chosen_action IS NOT NULL AND chosen_action <> 'wait'
                  ), 0)::float AS avg_ev
                FROM treatment_decisions
                WHERE mode = ANY(:modes)
                """
            ),
            {"modes": modes},
        ).mappings().first()
    if not row or not row["decisions"]:
        return None
    weeks = float(row["weeks"] or 0.0)
    cases = int(row["cases"] or 0)
    customers = int(row["customers"] or 0)
    return {
        "controlLabelled": int(row["control_labelled"] or 0),
        "controlCured": int(row["control_cured"] or 0),
        "controlCureRate": (
            row["control_cured"] / row["control_labelled"]
            if row["control_labelled"]
            else None
        ),
        "casesPerWeek": (cases / weeks) if weeks > 0.05 else None,
        # Measured clustering: cases per customer in the observed window. Feeds
        # the design effect directly rather than being assumed away.
        "casesPerCustomer": (cases / customers) if customers else 1.0,
        "avgExpectedValue": float(row["avg_ev"] or 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", type=int, default=50_000, help="accounts under management")
    ap.add_argument("--delinquency", type=float, default=0.05, help="share delinquent")
    ap.add_argument(
        "--cases-per-week",
        type=float,
        default=None,
        help=(
            "new delinquency cases a week; defaults to the delinquent population "
            "divided by one EMI cycle"
        ),
    )
    ap.add_argument(
        "--design-effect",
        type=float,
        default=1.0,
        help=(
            "clustering inflation for repeat borrowers, 1 + (cases_per_customer - 1)"
            " * ICC. 1.0 assumes every case is a different person."
        ),
    )
    ap.add_argument("--control-cure", type=float, default=DEFAULT_CONTROL_CURE)
    ap.add_argument(
        "--mde",
        type=float,
        default=DEFAULT_MDE,
        help="minimum detectable effect in absolute cure-rate points",
    )
    ap.add_argument("--alpha", type=float, default=DEFAULT_ALPHA)
    ap.add_argument("--power", type=float, default=DEFAULT_POWER)
    ap.add_argument(
        "--value-per-cure",
        type=float,
        default=None,
        help="₹ recovered per incremental cure; defaults to the logged average EV",
    )
    ap.add_argument("--from-db", action="store_true", help="use measured inputs where available")
    ap.add_argument("--include-simulated", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not 0.0 < args.mde < 1.0:
        logger.error("--mde must be a fraction, e.g. 0.05 for five points")
        return 2

    control_cure = args.control_cure
    per_week = args.cases_per_week or (args.book * args.delinquency / DEFAULT_CASE_WEEKS)
    value_per_cure = args.value_per_cure or 0.0
    design_effect = max(1.0, args.design_effect)
    provenance = {
        "controlCure": "assumed",
        "casesPerWeek": "assumed",
        "designEffect": "assumed",
    }

    if args.from_db:
        from env_loader import load_env

        load_env()
        found = observed(args.include_simulated)
        if not found:
            logger.warning("no decisions logged yet — every input below is a planning figure")
        else:
            # A cure rate from forty labelled control rows is not a cure rate.
            # The threshold is deliberately blunt: this script exists to stop
            # people acting on numbers that cannot support the weight.
            if found["controlCureRate"] is not None and found["controlLabelled"] >= 100:
                control_cure = found["controlCureRate"]
                provenance["controlCure"] = f"measured ({found['controlLabelled']} labelled)"
            elif found["controlLabelled"]:
                logger.warning(
                    "control arm has %d labelled outcomes — too few to take a cure rate "
                    "from, keeping the planning figure",
                    found["controlLabelled"],
                )
            if found["casesPerWeek"]:
                per_week = found["casesPerWeek"]
                provenance["casesPerWeek"] = "measured"
            if args.design_effect == 1.0 and found["casesPerCustomer"] > 1.0:
                # ICC 0.2 is a planning figure for "the same borrower behaves
                # somewhat like themselves across episodes". It is the one
                # number here that cannot be measured until the arm has run,
                # which is the usual chicken-and-egg of a power calculation.
                design_effect = 1.0 + (found["casesPerCustomer"] - 1.0) * 0.2
                provenance["designEffect"] = (
                    f"measured clustering ({found['casesPerCustomer']:.2f}"
                    " cases/customer), ICC assumed 0.2"
                )
            if args.value_per_cure is None and found["avgExpectedValue"]:
                value_per_cure = found["avgExpectedValue"] / max(0.01, args.mde)

    rows: list[dict[str, Any]] = []
    for fraction in FRACTIONS:
        ratio = (1.0 - fraction) / fraction
        n_control, n_treated = sample_size(
            p_control=control_cure,
            mde=args.mde,
            ratio=ratio,
            alpha=args.alpha,
            power=args.power,
            design_effect=design_effect,
        )
        total = n_control + n_treated
        weeks = total / per_week if per_week > 0 else float("inf")
        # What the arm costs: the incremental cures it deliberately forgoes.
        forgone = n_control * args.mde * value_per_cure
        rows.append(
            {
                "controlFraction": fraction,
                "controlN": n_control,
                "treatedN": n_treated,
                "totalDecisions": total,
                "weeks": round(weeks, 1) if weeks != float("inf") else None,
                "forgoneRecoveryInr": round(forgone, 0),
            }
        )

    verdict = _verdict(rows, per_week)
    payload = {
        "inputs": {
            "book": args.book,
            "delinquency": args.delinquency,
            "casesPerWeek": round(per_week, 1),
            "designEffect": round(design_effect, 3),
            "controlCureRate": round(control_cure, 4),
            "minimumDetectableEffect": args.mde,
            "alpha": args.alpha,
            "power": args.power,
            "valuePerIncrementalCureInr": round(value_per_cure, 2),
            "provenance": provenance,
        },
        "curve": rows,
        "verdict": verdict,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print()
    print(f"  book {args.book:,} at {args.delinquency:.0%} delinquent"
          f"  ->  {per_week:,.0f} cases/week ({provenance['casesPerWeek']})")
    if design_effect > 1.0:
        print(f"  design effect {design_effect:.2f} ({provenance['designEffect']})")
    print(f"  detecting a {args.mde:.0%}-point lift on a {control_cure:.1%} control-arm"
          f" cure rate ({provenance['controlCure']})")
    print(f"  at alpha={args.alpha}, power={args.power:.0%}, two-sided")
    print()
    print(f"  {'control':>8}  {'control n':>10}  {'treated n':>10}  {'total':>10}"
          f"  {'weeks':>7}  {'forgone ₹':>12}")
    print("  (n is cases — one delinquency episode each, not one decision each)")
    print(f"  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*7}  {'-'*12}")
    for r in rows:
        weeks = f"{r['weeks']:.1f}" if r["weeks"] is not None else "never"
        print(
            f"  {r['controlFraction']:>7.0%}  {r['controlN']:>10,}  {r['treatedN']:>10,}"
            f"  {r['totalDecisions']:>10,}  {weeks:>7}  {r['forgoneRecoveryInr']:>12,.0f}"
        )
    print()
    for line in verdict["notes"]:
        print(f"  {line}")
    print()
    return 0


def _verdict(rows: list[dict[str, Any]], per_week: float) -> dict[str, Any]:
    """Whether this book can power the arm, and what to do if it cannot."""
    feasible = [r for r in rows if r["weeks"] is not None and r["weeks"] <= 26]
    notes: list[str] = []
    if per_week <= 0:
        return {
            "powerable": False,
            "notes": ["No case volume at all — run the sweep before sizing an arm."],
        }
    if not feasible:
        fastest = min(rows, key=lambda r: r["weeks"] or float("inf"))
        notes.append(
            f"NOT POWERABLE inside two quarters. The fastest split ({fastest['controlFraction']:.0%})"
            f" still needs {fastest['weeks']:.0f} weeks."
        )
        notes.append(
            "This is a product-strategy finding, not a tuning problem. Three ways out,"
        )
        notes.append(
            "  in descending order of honesty: raise the minimum detectable effect and"
        )
        notes.append(
            "  admit the arm can only find large effects; pool the arm across tenants"
        )
        notes.append(
            "  (which is §19.1, and a contract question before it is a statistics one);"
        )
        notes.append(
            "  or ship documented planning priors and tell the client the first quarter"
        )
        notes.append("  is calibration.")
        return {"powerable": False, "notes": notes}

    cheapest = min(feasible, key=lambda r: r["forgoneRecoveryInr"])
    fastest = min(feasible, key=lambda r: r["weeks"])
    notes.append(
        f"Powerable. Fastest: {fastest['controlFraction']:.0%} control in"
        f" {fastest['weeks']:.0f} weeks, forgoing ~₹{fastest['forgoneRecoveryInr']:,.0f}."
    )
    if cheapest["controlFraction"] != fastest["controlFraction"]:
        notes.append(
            f"Cheapest: {cheapest['controlFraction']:.0%} control in"
            f" {cheapest['weeks']:.0f} weeks, forgoing ~₹{cheapest['forgoneRecoveryInr']:,.0f}."
        )
    notes.append(
        "Pick a point on that trade-off deliberately. This script will not pick one:"
    )
    notes.append(
        "  the difference between the two rows is real borrowers who were not contacted."
    )
    return {"powerable": True, "notes": notes}


if __name__ == "__main__":
    raise SystemExit(main())
