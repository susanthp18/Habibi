"""Champion/challenger — §15's promotion gate, with a memory.

Everything up to this gate already existed. The corpus generator produces the
log, the trainers fit challengers against it, and ``ope.py`` scores a candidate
policy off-policy. What was missing is the step where somebody decides a
challenger is better and the decision leaves a trace.

**Promotion is refused by default.** Every rule below is a reason to say no, and
there is no positive rule: a challenger is promoted when nothing objects. That
asymmetry is deliberate — the cost of not promoting a good model is some
foregone lift, and the cost of promoting a bad one is a book's worth of
decisions made confidently wrong.

**The registry gates and records. It does not serve.** ``models.load_*`` remains
a pure file read: it runs in a service on the audio path of a live call, and a
database between a scorer and its coefficients trades a real availability
guarantee for a bookkeeping one. :func:`promote` is what copies the challenger
into the serving path, and the sha is what makes that claim checkable — a file
edited after promotion is detectable by :func:`verify`, which is the failure a
registry of version strings alone could not see.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from agent_core.treatment import evaluation_seal, models, prereg
from agent_core.clock import utc_now as _now

logger = logging.getLogger(__name__)

TARGETS = ("reach", "timing", "uplift")

STATUS_CHALLENGER = "challenger"
STATUS_CHAMPION = "champion"
STATUS_RETIRED = "retired"
STATUS_REJECTED = "rejected"

#: Where each target serves from. The same defaults ``models._path`` resolves,
#: and the reason promotion is a file copy rather than a pointer update: one
#: path per target means the serving state is a thing you can look at.
SERVING_PATHS: dict[str, str] = {
    "reach": "models/treatment_reach.json",
    "timing": "models/treatment_timing.json",
    "uplift": "models/treatment_uplift.json",
}

#: Minimum improvement a challenger must show before it may serve.
#: Not zero: a challenger that ties the champion is a challenger that costs a
#: deployment, a retraining cadence and an explanation, and buys nothing.
#:
#: **The quantity compared against it is the lower bound, not the point
#: estimate.** §8.12 gate 7: "the **confidence sequence's** lower bound on ΔEV
#: in rupees per borrower clears a margin". A point estimate above a floor is a
#: coin that landed the right way up; `ope.delta` produces the bound and
#: `evaluation["lcb"]` is where it travels.
MIN_HOLDOUT_LIFT = 0.005

#: §8.12 gate 7's margin, as a multiple of the **measured** per-borrower
#: recovery standard deviation.
#:
#: Not a rupee constant, and §8.12 says why at length: "nobody had computed the
#: dispersion of per-case recovery: at a ₹3,000 mean and CV 1–4, at 14,600 cases
#: with DE 3, the SE of Δ per case is ₹108–₹430, so a flat ₹1.50 margin is
#: 0.3–1.4% of one standard error and does literally nothing." A margin that is
#: a fraction of the book's own dispersion scales with the book; a rupee figure
#: written down once does not.
VALUE_MARGIN_SD_MULTIPLE = 0.05

# --- The corpus gates -------------------------------------------------------
# §8.10's rung 1, as numbers rather than as a paragraph. They are here rather
# than in the trainer because the trainer is not what promotes: a model fitted
# on forty borrowers is not a defect, it is a draft, and the gate is where a
# draft stops being allowed to decide who gets called.
#
# §8.12: "No artefact is promoted while any gate cannot be *evaluated*: an
# unevaluable gate is a refusal, recorded as considered-and-declined." So a
# corpus this cannot read produces an objection, never silence -- the failure
# mode being avoided is a gate that returns [] because the query fell over.

#: Distinct **customers**, not rows. §8.7: the causal unit is the borrower, and
#: `[metrics-causal-unit-is-decision-not-customer]` is what counting rows here
#: would re-introduce.
MIN_TREATED_CUSTOMERS = 150
MIN_CONTROL_CUSTOMERS = 200

#: Below forty clusters per arm the cluster bootstrap of Gate 8 stops being
#: trustworthy and the wild bootstrap with t(G-1) critical values takes over.
#: A promotion is not the place to be doing that for the first time.
MIN_CLUSTERS_PER_ARM = 40

#: The arm name that means "we deliberately did nothing", as written by
#: ``explore.choose``. Named once so the corpus gate and the artifact's own
#: ``controlArm`` field cannot drift apart.
CONTROL_VARIANT = "null_treatment"


class PromotionRefused(Exception):
    """Raised with the reason. The reason is the useful part."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()



def register(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    path: str | Path,
    evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an artifact as a challenger. Idempotent on (version, sha).

    Registration validates nothing about quality — a model too weak to promote
    is still worth having in the ledger, because "we fitted this and it lost" is
    a finding, and a registry that only remembers winners cannot tell you how
    many challengers it took.

    It does validate that the file *loads*, using the same loader the serving
    path uses. A challenger that this build cannot read is not a challenger; it
    is a file, and finding that out at promotion time would find it out on the
    day somebody is trying to ship.
    """
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}")
    p = Path(path)
    artifact = models.load_artifact(p, expect_target=target, allow_simulated=True)
    if artifact is None:
        raise PromotionRefused(
            f"{p} does not load as a {target} artifact under this build — "
            "the loader's own warning says why"
        )

    metrics_raw: dict[str, Any] = {}
    try:
        metrics_raw = (json.loads(p.read_text(encoding="utf-8")) or {}).get("metrics") or {}
    except (OSError, json.JSONDecodeError):  # pragma: no cover - load_artifact caught it
        metrics_raw = {}

    row_id = f"TMR-{uuid.uuid4().hex[:12].upper()}"
    sha = _sha(p)
    conn.execute(
        text(
            """
            INSERT INTO treatment_model_registry
              (id, tenant_id, target, version, artifact_sha, artifact_path,
               status, corpus, n_samples, control_n, segments_promoted,
               metrics, evaluation)
            VALUES
              (:id, :tenant, :target, :version, :sha, :path,
               'challenger', :corpus, :n, :control_n, :segments,
               CAST(:metrics AS jsonb), CAST(:evaluation AS jsonb))
            ON CONFLICT (tenant_id, target, version, artifact_sha)
            DO UPDATE SET evaluation = COALESCE(
                CAST(:evaluation AS jsonb), treatment_model_registry.evaluation
            )
            """
        ),
        {
            "id": row_id,
            "tenant": tenant_id,
            "target": target,
            "version": artifact.version,
            "sha": sha,
            "path": str(p),
            "corpus": artifact.corpus,
            "n": artifact.n_samples,
            "control_n": artifact.control_n,
            "segments": len(artifact.segments),
            "metrics": json.dumps(metrics_raw),
            "evaluation": json.dumps(dict(evaluation)) if evaluation else None,
        },
    )
    return {"target": target, "version": artifact.version, "sha": sha, "path": str(p)}


def champion(conn: Any, *, tenant_id: str, target: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT * FROM treatment_model_registry
            WHERE tenant_id = :tenant AND target = :target AND status = 'champion'
            """
        ),
        {"tenant": tenant_id, "target": target},
    ).mappings().first()
    return dict(row) if row else None


def history(conn: Any, *, tenant_id: str, target: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            SELECT id, target, version, status, corpus, n_samples, control_n,
                   segments_promoted, registered_at, promoted_at, promoted_by,
                   retired_at, reason, metrics, evaluation
            FROM treatment_model_registry
            WHERE tenant_id = :tenant
              -- CAST before the null test. A bare ``:target IS NULL`` gives
              -- the planner nothing to infer the parameter's type from when
              -- the value is NULL, and Postgres refuses the statement outright
              -- with "could not determine data type of parameter $2". The same
              -- trap as the mandate feature query and the decision log's
              -- jsonb_build_object before it -- an optional filter is where it
              -- always shows up, because the unfiltered call is the one nobody
              -- tries until later.
              AND (CAST(:target AS TEXT) IS NULL OR target = CAST(:target AS TEXT))
            ORDER BY registered_at DESC
            LIMIT :limit
            """
        ),
        {"tenant": tenant_id, "target": target, "limit": max(1, int(limit))},
    ).mappings().all()
    return [dict(r) for r in rows]


def _refuse(reason: str) -> None:
    raise PromotionRefused(reason)


def corpus_objections(conn: Any, *, tenant_id: str) -> list[str]:
    """Every reason this corpus cannot yet support a promotion, with its number.

    Separated and public because the number is the useful part. "Refused" tells
    an operator to try again later; "0 mature cases, 21 distinct customers"
    tells them the wait is months and that the labeller, not the trainer, is
    what is next.

    Reads inside ``begin_nested`` per W0: this runs on a connection the caller
    lent us, and a failed read outside a savepoint aborts *their* transaction —
    the abort cascade W8a shipped and W9a's notes describe.
    """
    if conn is None:
        return [
            "no connection, so the corpus gates could not be evaluated at all — "
            "§8.12 makes an unevaluable gate a refusal"
        ]
    try:
        with conn.begin_nested():
            row = conn.execute(
                text(
                    """
                    SELECT
                      count(*) FILTER (
                        WHERE label_mature_at IS NOT NULL AND label_mature_at <= now()
                      ) AS mature,
                      count(DISTINCT customer_id) FILTER (
                        WHERE variant IS DISTINCT FROM :control
                      ) AS treated_customers,
                      count(DISTINCT customer_id) FILTER (
                        WHERE variant = :control
                      ) AS control_customers,
                      count(*) FILTER (WHERE reach_outcome IS NOT NULL) AS reach_labelled,
                      count(*) FILTER (WHERE cure_outcome IS NOT NULL) AS cure_labelled
                    FROM treatment_decisions
                    WHERE tenant_id = :tenant AND mode = 'live'
                    """
                ),
                {"tenant": tenant_id, "control": CONTROL_VARIANT},
            ).mappings().first()
    except Exception as exc:
        logger.exception("corpus gate could not be evaluated for %s", tenant_id)
        return [
            f"the corpus gates could not be evaluated ({exc.__class__.__name__}), "
            "and §8.12 makes an unevaluable gate a refusal rather than a pass"
        ]

    counts = dict(row or {})
    mature = int(counts.get("mature") or 0)
    treated = int(counts.get("treated_customers") or 0)
    control = int(counts.get("control_customers") or 0)
    reach_labelled = int(counts.get("reach_labelled") or 0)
    cure_labelled = int(counts.get("cure_labelled") or 0)

    out: list[str] = []
    if mature <= 0:
        out.append(
            "0 decisions have reached the primary horizon — a promotion gate on "
            "immature labels is a promotion gate on nothing (§8.10)"
        )
    if treated < MIN_TREATED_CUSTOMERS:
        out.append(
            f"{treated} treated customers against a floor of {MIN_TREATED_CUSTOMERS} "
            "(§8.10 rung 1, counted as borrowers rather than rows)"
        )
    if control < MIN_CONTROL_CUSTOMERS:
        out.append(
            f"{control} control customers against a floor of {MIN_CONTROL_CUSTOMERS} "
            "(§8.10 rung 1)"
        )
    if min(treated, control) < MIN_CLUSTERS_PER_ARM:
        out.append(
            f"{min(treated, control)} clusters in the smaller arm against the "
            f"{MIN_CLUSTERS_PER_ARM} the cluster bootstrap needs (§8.12 gate 8)"
        )
    if not reach_labelled or not cure_labelled:
        out.append(
            f"{reach_labelled} rows carry a reach label and {cure_labelled} carry a "
            "cure label — there is no outcome to have fitted against"
        )
    return out


def value_margin(conn: Any, *, tenant_id: str) -> tuple[float | None, str]:
    """§8.12 gate 7's margin, measured. Returns ``(margin, basis)``.

    ``margin`` is ``None`` when the panel cannot measure the dispersion, and
    then ``basis`` says why. That is a refusal, not a licence to substitute a
    constant: the whole point of §8.12's worked example is that an unmeasured
    margin is indistinguishable from no margin, and the flat ₹1.50 it describes
    passed every promotion it was ever shown.

    The unit is the **borrower**, so cases are summed per customer before the
    standard deviation is taken. Taking it over cases instead would divide by a
    count of sweeps and report a dispersion smaller than the one a promotion is
    actually exposed to.
    """
    from agent_core.treatment import schema_ready

    if conn is None:
        return None, "no connection, so the per-borrower recovery SD could not be measured"
    if not schema_ready.has_table(conn, "analysis_panel"):
        # Expected on a database behind W7, and not worth a stack trace. The
        # answer is the same either way — unmeasurable is a refusal — but a
        # genuine query failure should stay loud, which is why this is a probe
        # rather than a broader except.
        return None, (
            "`analysis_panel` is absent on this database (W7, sql/26), so there "
            "is no borrower-level reward to take a standard deviation of"
        )
    try:
        with conn.begin_nested():
            row = conn.execute(
                text(
                    """
                    SELECT count(*)::int AS borrowers,
                           stddev_samp(total) AS sd,
                           avg(total) AS mean
                    FROM (
                      SELECT customer_id, sum(reward_inr)::float AS total
                      FROM analysis_panel
                      WHERE tenant_id = :tenant AND mature IS TRUE
                        AND reward_inr IS NOT NULL
                      GROUP BY customer_id
                    ) per_borrower
                    """
                ),
                {"tenant": tenant_id},
            ).mappings().first()
    except Exception as exc:
        logger.exception("value margin could not be measured for %s", tenant_id)
        return None, (
            f"the per-borrower recovery SD could not be measured "
            f"({exc.__class__.__name__}) — `analysis_panel` is W7's table and "
            "this database may not carry it"
        )

    counts = dict(row or {})
    borrowers = int(counts.get("borrowers") or 0)
    sd = counts.get("sd")
    if borrowers < 2 or sd is None:
        return None, (
            f"{borrowers} borrowers carry a mature panel reward, so the recovery "
            "SD has no dispersion to measure — §8.12 gate 7's margin is a "
            "multiple of that SD and there is nothing to take a multiple of"
        )
    sd = float(sd)
    if not math.isfinite(sd) or sd <= 0:
        return None, "the measured per-borrower recovery SD is not a positive finite number"
    return (
        VALUE_MARGIN_SD_MULTIPLE * sd,
        f"{VALUE_MARGIN_SD_MULTIPLE} × ₹{sd:,.2f}, the measured per-borrower "
        f"recovery SD over {borrowers} borrowers with mature panel rewards",
    )


def _value_objections(
    conn: Any, *, tenant_id: str, evaluation: Mapping[str, Any]
) -> list[str]:
    """§8.12 gate 7 — the lower bound against a measured margin.

    Three ways to fail, and the middle one is the one this wave exists for: an
    evaluation that reports a lift and no bound is an evaluation from before the
    gate changed shape, and accepting its ``lift`` as a fallback would make the
    new gate optional. §8.12: "A gate with a documented bypass is worse than no
    gate, because it will be cited as evidence that the property was tested."
    """
    out: list[str] = []
    lcb = evaluation.get("lcb")
    if isinstance(lcb, Mapping):  # an ope.sequence.Bound, serialised
        if lcb.get("refusal"):
            return [f"the confidence sequence could not be computed: {lcb['refusal']}"]
        lcb = lcb.get("lower")
    if lcb is None:
        if evaluation.get("lift") is not None:
            return [
                "the evaluation reports a point estimate and no confidence-sequence "
                "lower bound. §8.12 gate 7 promotes on the bound, and a point "
                "estimate above a floor is a coin that landed the right way up — "
                "re-run scripts/evaluate_policy.py under this build"
            ]
        return ["the evaluation carries no lower bound (`lcb`)"]

    bound = float(lcb)
    if not math.isfinite(bound):
        return [f"the lower bound is {lcb}, which is not a number a gate can compare"]
    if bound < MIN_HOLDOUT_LIFT:
        out.append(
            f"the lower bound is {bound:+.4f}, below the {MIN_HOLDOUT_LIFT:+.4f} "
            "floor — a challenger that cannot be shown to beat the champion costs "
            "a deployment and buys nothing"
        )

    margin, basis = value_margin(conn, tenant_id=tenant_id)
    if margin is None:
        out.append(
            f"gate 7's margin could not be measured: {basis}. §8.12 makes an "
            "unevaluable gate a refusal, and substituting a constant here is the "
            "flat ₹1.50 margin that passed everything it was shown"
        )
    elif bound < margin:
        out.append(
            f"the lower bound is {bound:+.4f} against a margin of {margin:+.4f} "
            f"({basis})"
        )
    return out


def check(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    path: str | Path,
    evaluation: Mapping[str, Any] | None,
    allow_simulated: bool = False,
    promoted_by: str = "",
) -> list[str]:
    """Every reason this challenger may not serve. Empty means it may.

    Separated from :func:`promote` so the same rules can answer "would this be
    promoted?" without a transaction, which is what a CI check and a dry run
    both want. There is no way to promote without passing through here.
    """
    objections: list[str] = []
    p = Path(path)
    # Loaded permissively so that a simulated artifact reaches the corpus check
    # below and gets the objection that actually explains it, rather than being
    # refused at the door as unparseable.
    artifact = models.load_artifact(p, expect_target=target, allow_simulated=True)
    if artifact is None:
        return [f"{p} does not load as a {target} artifact under this build"]

    # Gate 2, and it comes first because everything after it is a statement
    # about a file. An evaluation that describes a different artifact makes
    # every objection below it a claim about something that is not being
    # promoted — including the absence of objections.
    objections.extend(evaluation_seal.objections(evaluation, artifact_sha=_sha(p)))
    objections.extend(corpus_objections(conn, tenant_id=tenant_id))

    if artifact.corpus != "live" and not allow_simulated:
        # The simulator writes a corpus that looks exactly like a real one,
        # which is the point of it, and the consequence is that a model fitted
        # on it looks exactly like a real model. Promoting one would put a model
        # of a synthetic book in front of borrowers who exist.
        objections.append(
            f"fitted on the {artifact.corpus} corpus — promoting it would serve a "
            "model of a book that does not exist"
        )

    if evaluation is None:
        objections.append(
            "no evaluation attached. Promotion is gated on a lower bound, and an "
            "artifact with good training metrics and no holdout is precisely the "
            "thing the gate exists to stop"
        )
    else:
        objections.extend(_value_objections(conn, tenant_id=tenant_id, evaluation=evaluation))
        if evaluation.get("trustworthy") is False:
            # The diagnostics, not the estimate. A number computed from forty
            # effective samples wearing ten thousand samples' confidence
            # interval is worse than no number, because it is a number.
            objections.append(
                "the evaluation reports itself as untrustworthy — read its effective "
                "sample size and unsupported fraction before anything else"
            )
        for reason in evaluation.get("objections") or []:
            objections.append(f"the evaluation refuses itself: {reason}")

    # Gates 14 and 15. Last, because they are about people rather than about the
    # file, and an operator reading a refusal wants the arithmetic first.
    objections.extend(
        prereg.objections(
            conn,
            tenant_id=tenant_id,
            target=target,
            evaluation=evaluation,
            promoted_by=promoted_by,
        )
    )

    if target == "uplift":
        if not artifact.control_arm:
            objections.append(
                "names no randomised control arm, so it cannot be causal — it is a "
                "response model wearing the word uplift, and it will rank self-curers "
                "first"
            )
        if artifact.control_n < models.MIN_CONTROL_N:
            objections.append(
                f"control arm holds {artifact.control_n} observations "
                f"(min {models.MIN_CONTROL_N})"
            )
        ate = (evaluation or {}).get("ate")
        if ate is not None and float(ate) <= 0:
            objections.append(
                f"measured ATE is {float(ate):+.4f} — the control arm says the "
                "logging policy does not beat doing nothing, and promoting a τ "
                "fitted against it would promote that finding into the score"
            )

    if artifact.age_days() is not None and artifact.age_days() > models._max_age_days() > 0:
        objections.append(f"artifact is {artifact.age_days():.0f} days old")

    return objections


def promote(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    path: str | Path,
    evaluation: Mapping[str, Any] | None,
    promoted_by: str,
    reason: str = "",
    allow_simulated: bool = False,
    serving_path: str | Path | None = None,
) -> dict[str, Any]:
    """Install a challenger as champion, or refuse and say why.

    Order matters: the gate runs, the previous champion is retired, the new row
    is marked champion, and only then is the file copied into the serving path.
    A copy that happened before the ledger agreed would leave a model serving
    that the registry does not know about — which is the state this module
    exists to make impossible.
    """
    objections = check(
        conn,
        tenant_id=tenant_id,
        target=target,
        path=path,
        evaluation=evaluation,
        allow_simulated=allow_simulated,
        promoted_by=promoted_by,
    )
    if objections:
        raise PromotionRefused("; ".join(objections))

    p = Path(path)
    sha = _sha(p)
    artifact = models.load_artifact(p, expect_target=target, allow_simulated=True)
    assert artifact is not None  # check() already loaded it

    register(conn, tenant_id=tenant_id, target=target, path=p, evaluation=evaluation)

    previous = champion(conn, tenant_id=tenant_id, target=target)
    if previous and previous["artifact_sha"] == sha:
        # Re-promoting what is already champion. Retiring it first and then
        # marking it champion again would leave a row that is simultaneously
        # champion and retired, which is a state no reader of this ledger should
        # ever have to interpret.
        previous = None
    if previous:
        conn.execute(
            text(
                """
                UPDATE treatment_model_registry
                SET status = 'retired', retired_at = :now,
                    reason = COALESCE(reason, '') ||
                             ' | superseded by ' || :version
                WHERE id = :id
                """
            ),
            {"id": previous["id"], "now": _now(), "version": artifact.version},
        )

    # The licence travels onto the champion row itself, so "why is this model
    # serving?" resolves to a filed claim rather than to the evaluation blob it
    # happens to be stored next to.
    from agent_core.treatment import schema_ready

    licence = ""
    if schema_ready.w11_ready(conn):
        licence = ", pre_registration_id = :prereg"
    conn.execute(
        text(
            f"""
            UPDATE treatment_model_registry
            SET status = 'champion', promoted_at = :now, promoted_by = :by,
                reason = :reason,
                evaluation = COALESCE(CAST(:evaluation AS jsonb), evaluation)
                {licence}
            WHERE tenant_id = :tenant AND target = :target
              AND version = :version AND artifact_sha = :sha
            """
        ),
        {
            "tenant": tenant_id,
            "target": target,
            "version": artifact.version,
            "sha": sha,
            "now": _now(),
            "by": promoted_by,
            "reason": reason or None,
            "evaluation": json.dumps(dict(evaluation)) if evaluation else None,
            **(
                {"prereg": str((evaluation or {}).get(prereg.PREREG_FIELD) or "") or None}
                if licence
                else {}
            ),
        },
    )

    destination = Path(serving_path or SERVING_PATHS[target])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if p.resolve() != destination.resolve():
        shutil.copyfile(p, destination)
    logger.info(
        "promoted %s %s (sha %s) to %s by %s",
        target, artifact.version, sha[:12], destination, promoted_by,
    )
    return {
        "target": target,
        "version": artifact.version,
        "sha": sha,
        "servingPath": str(destination),
        "retired": previous["version"] if previous else None,
    }


def reject(
    conn: Any, *, tenant_id: str, target: str, version: str, sha: str, reason: str
) -> None:
    """Mark a challenger as considered and turned down.

    Distinct from simply leaving it a challenger: "we looked at this and said
    no" and "this is waiting to be looked at" are different facts, and a queue
    that cannot tell them apart grows without bound.
    """
    conn.execute(
        text(
            """
            UPDATE treatment_model_registry
            SET status = 'rejected', reason = :reason
            WHERE tenant_id = :tenant AND target = :target
              AND version = :version AND artifact_sha = :sha
              AND status = 'challenger'
            """
        ),
        {"tenant": tenant_id, "target": target, "version": version, "sha": sha, "reason": reason},
    )


def verify(conn: Any, *, tenant_id: str) -> list[dict[str, Any]]:
    """Does what is serving match what was promoted?

    The question a registry of version strings cannot answer. A file edited or
    replaced after promotion keeps its version string and its filename, and
    every log line downstream keeps naming the promoted version while different
    coefficients decide whether borrowers are contacted.
    """
    out: list[dict[str, Any]] = []
    for target in TARGETS:
        record = champion(conn, tenant_id=tenant_id, target=target)
        serving = Path(SERVING_PATHS[target])
        if record is None:
            out.append({
                "target": target,
                "state": "unregistered" if serving.exists() else "absent",
                "detail": (
                    "a file is serving that no promotion produced"
                    if serving.exists()
                    else "no champion and no file — the EV priors are answering"
                ),
            })
            continue
        if not serving.exists():
            out.append({
                "target": target,
                "state": "missing",
                "version": record["version"],
                "detail": "promoted, but the serving file is gone",
            })
            continue
        actual = _sha(serving)
        matches = actual == record["artifact_sha"]
        out.append({
            "target": target,
            "state": "ok" if matches else "drifted",
            "version": record["version"],
            "promotedAt": record["promoted_at"],
            "promotedBy": record["promoted_by"],
            "detail": (
                "serving what was promoted"
                if matches
                else f"serving sha {actual[:12]}, promoted {record['artifact_sha'][:12]}"
            ),
        })
    return out
