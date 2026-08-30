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
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from agent_core.treatment import models

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

#: Minimum holdout improvement a challenger must show before it may serve.
#: Not zero: a challenger that ties the champion is a challenger that costs a
#: deployment, a retraining cadence and an explanation, and buys nothing. The
#: unit is whatever the evaluation reports as ``lift``.
MIN_HOLDOUT_LIFT = 0.005


class PromotionRefused(Exception):
    """Raised with the reason. The reason is the useful part."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def check(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    path: str | Path,
    evaluation: Mapping[str, Any] | None,
    allow_simulated: bool = False,
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
            "no evaluation attached. Promotion is gated on holdout lift, and an "
            "artifact with good training metrics and no holdout is precisely the "
            "thing the gate exists to stop"
        )
    else:
        lift = evaluation.get("lift")
        if lift is None:
            objections.append("evaluation carries no lift figure")
        elif float(lift) < MIN_HOLDOUT_LIFT:
            objections.append(
                f"holdout lift {float(lift):+.4f} is below the {MIN_HOLDOUT_LIFT:+.4f} "
                "floor — a challenger that ties the champion costs a deployment and "
                "buys nothing"
            )
        if evaluation.get("trustworthy") is False:
            # The diagnostics, not the estimate. A number computed from forty
            # effective samples wearing ten thousand samples' confidence
            # interval is worse than no number, because it is a number.
            objections.append(
                "the evaluation reports itself as untrustworthy — read its effective "
                "sample size and unsupported fraction before anything else"
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

    conn.execute(
        text(
            """
            UPDATE treatment_model_registry
            SET status = 'champion', promoted_at = :now, promoted_by = :by,
                reason = :reason,
                evaluation = COALESCE(CAST(:evaluation AS jsonb), evaluation)
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
