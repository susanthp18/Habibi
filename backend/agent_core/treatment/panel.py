"""W7 · the analysis panel — one row per case, so `m` is a measurement.

§8.7 of ``docs/design/engines-production-design.md`` fixes the unit of analysis as the
**case**, and the design effect ``DE = 1 + (m - 1) * ICC`` — how many independent
observations a given number of decisions is actually worth — is computed from
cases per customer. Everything downstream of that number moves with it: the
minimum detectable effect as ``sqrt(DE)``, the required sample size as ``DE``.

**The case is a delinquency spell, not a day.** ``treatment_decisions.trigger_ref``
carries the borrower's local date because the sweep needs it as a daily dedupe
key — "one decision per account per local day" (``sweep.py``). Counted that way,
a borrower ninety days delinquent contributes ninety cases, and the design effect
degenerates to the 12.8 §8.7 warns about. Measured on this book on 2026-09-09:
268 ``dpd_tick`` day-cases over 21 customers, which is m = 12.8 exactly as the
design predicted, collapsing to **40 spells**, m = 1.9. DE at ICC 0.2 falls from
3.36 to 1.18 — a factor of 1.7 on the MDE, 2.8 on the sample size.

So the spell is derived **here**, at panel-build time, and the serving path does
not move. A spell breaks when the borrower is not seen delinquent on consecutive
local days: a gap in the daily tick is the sweep saying the account was not
delinquent that day. Non-``dpd_tick`` triggers are already one case per event and
keep their ``trigger_ref`` unchanged.

The builder is idempotent — a case is upserted on its key, never appended — so a
re-run over an overlapping window produces the same panel.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Sequence

from sqlalchemy import text

from agent_core.treatment import cancel

logger = logging.getLogger(__name__)

#: Modes whose decisions may enter the panel. ``simulated`` never does: the
#: simulator is demoted (§15.3) and may exercise code paths but may not select a
#: parameter, and a panel row is an input to every published number. ``off`` has
#: no decision to analyse.
PANEL_MODES: tuple[str, ...] = ("shadow", "live")

#: A case whose decisions were all cancelled by our own executor carries no
#: outcome that is the borrower's. §11.5: cancelled is censoring, not failure.
CENSORING_REASONS = cancel.REASONS

#: A cancellation the log cannot attribute. Not in :mod:`cancel`'s vocabulary
#: because it is not a reason the executor can emit -- it is what a
#: logging-contract-v1 row looks like from here, `cancel_reason` having been
#: added after those rows were written. Measured on this book 2026-09-09: 1 of
#: the 48 cases is fully cancelled with no reason on any of its decisions.
UNATTRIBUTED_CENSOR = "unattributed"

SPELL_TRIGGER = "dpd_tick"


def _case_id(tenant: str, customer: str, account: str, kind: str, ref: str) -> str:
    digest = hashlib.sha256(
        "\x1f".join((tenant, customer, account, kind, ref)).encode("utf-8")
    ).hexdigest()
    return f"PNL-{digest[:24]}"


#: One statement, because the spell boundary is a window function over the
#: decision log and pulling the rows into Python to sessionise them would read
#: the whole corpus to compute a `lag`.
#:
#: `spell_ref` for dpd_tick: within (customer, account), order the distinct local
#: dates and open a new spell wherever the gap to the previous date exceeds one
#: day. Every decision in a spell then carries the spell's first date. Dates that
#: do not parse as dates -- test probes use `probe-<hex>` -- fall back to the raw
#: trigger_ref, which keeps them one case each rather than dropping them.
_CASES = """
WITH scoped AS (
  SELECT d.*, COALESCE(d.account_id, '') AS acct,
         CASE
           WHEN d.trigger_kind = :spell_trigger
                AND d.trigger_ref ~ '^\\d{4}-\\d{2}-\\d{2}$'
           THEN d.trigger_ref::date
         END AS tick_day
    FROM treatment_decisions d
   WHERE d.mode = ANY(:modes)
     AND d.trigger_ref IS NOT NULL
     AND d.created_at >= :since
     AND (CAST(:tenant AS TEXT) IS NULL OR d.tenant_id = :tenant)
     AND (CAST(:customers AS TEXT[]) IS NULL OR d.customer_id = ANY(:customers))
),
marked AS (
  SELECT *,
         CASE
           WHEN tick_day IS NULL THEN 1
           WHEN lag(tick_day) OVER w IS NULL THEN 1
           WHEN tick_day - lag(tick_day) OVER w > 1 THEN 1
           ELSE 0
         END AS opens_spell
    FROM scoped
  WINDOW w AS (PARTITION BY tenant_id, customer_id, acct ORDER BY tick_day)
),
spelled AS (
  SELECT *,
         sum(opens_spell) OVER (
           PARTITION BY tenant_id, customer_id, acct ORDER BY tick_day
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
         ) AS spell_no
    FROM marked
),
keyed AS (
  SELECT *,
         CASE
           WHEN tick_day IS NULL THEN trigger_ref
           ELSE min(tick_day::text) OVER (
             PARTITION BY tenant_id, customer_id, acct, spell_no
           )
         END AS spell_ref
    FROM spelled
)
SELECT
  tenant_id, customer_id, acct AS account_id, trigger_kind, spell_ref,
  count(*)::int AS decisions,
  count(*) FILTER (WHERE enacted)::int AS enacted_decisions,
  min(created_at) AS first_decision_at,
  max(created_at) AS last_decision_at,
  -- The arm is frozen at the first decision on the case; a later row
  -- disagreeing is an epoch crossing and is recorded, not averaged.
  (array_agg(variant ORDER BY created_at))[1] AS variant,
  count(DISTINCT variant) FILTER (WHERE variant IS NOT NULL)::int AS variants_seen,
  -- Labels: the best evidence anywhere on the case. A case is reached if any
  -- attempt on it was, cured if any decision on it cured.
  max(reach_outcome) FILTER (WHERE reach_outcome IS NOT NULL) AS reach_outcome,
  max(cure_outcome) FILTER (WHERE cure_outcome IS NOT NULL) AS cure_outcome,
  max(observed_days)::int AS observed_days,
  bool_and(label_mature_at IS NOT NULL AND label_mature_at <= :now) AS mature,
  count(*) FILTER (WHERE outcome IS NOT NULL)::int AS labelled,
  count(*) FILTER (WHERE outcome = 'cancelled')::int AS cancelled,
  (array_agg(cancel_reason ORDER BY created_at)
     FILTER (WHERE cancel_reason IS NOT NULL))[1] AS censor_reason,
  max(label_definition_version) AS label_definition_version,
  min(logging_contract_version)::int AS logging_contract_version,
  array_agg(DISTINCT mode) AS modes
FROM keyed
GROUP BY tenant_id, customer_id, acct, trigger_kind, spell_ref
"""

_UPSERT = """
INSERT INTO analysis_panel (
  id, tenant_id, customer_id, account_id, trigger_kind, spell_ref,
  variant, randomised_at, decisions, enacted_decisions,
  reach_outcome, cure_outcome, reward_inr, observed_days, mature,
  censored, censor_reason, first_decision_at, last_decision_at,
  label_definition_version, logging_contract_version, modes, built_at
) VALUES (
  :id, :tenant_id, :customer_id, :account_id, :trigger_kind, :spell_ref,
  :variant, :randomised_at, :decisions, :enacted_decisions,
  :reach_outcome, :cure_outcome, :reward_inr, :observed_days, :mature,
  :censored, :censor_reason, :first_decision_at, :last_decision_at,
  :label_definition_version, :logging_contract_version, :modes, now()
)
ON CONFLICT (tenant_id, customer_id, account_id, trigger_kind, spell_ref)
DO UPDATE SET
  variant = EXCLUDED.variant,
  randomised_at = EXCLUDED.randomised_at,
  decisions = EXCLUDED.decisions,
  enacted_decisions = EXCLUDED.enacted_decisions,
  reach_outcome = EXCLUDED.reach_outcome,
  cure_outcome = EXCLUDED.cure_outcome,
  reward_inr = EXCLUDED.reward_inr,
  observed_days = EXCLUDED.observed_days,
  mature = EXCLUDED.mature,
  censored = EXCLUDED.censored,
  censor_reason = EXCLUDED.censor_reason,
  first_decision_at = EXCLUDED.first_decision_at,
  last_decision_at = EXCLUDED.last_decision_at,
  label_definition_version = EXCLUDED.label_definition_version,
  logging_contract_version = EXCLUDED.logging_contract_version,
  modes = EXCLUDED.modes,
  built_at = now()
"""

#: Rupees recovered on the case's account inside its own observation window.
#: From ``ledger_entries``, not ``payment_events`` -- that table's ``kind`` is
#: CHECK-constrained to ``'bounce'`` and is a returns ledger, so a recovery
#: figure read from it is structurally zero. ``metrics.causal`` learned this the
#: same way and the comment is kept here so the next reader does not re-learn it.
_REWARD = """
SELECT COALESCE(sum(le.amount), 0)::float AS recovered
  FROM ledger_entries le
  JOIN accounts a ON a.id = le.account_id
 WHERE le.type = 'payment'
   AND a.customer_id = :customer_id
   AND (CAST(:account_id AS TEXT) = '' OR le.account_id = :account_id)
   AND le.posted_at >= :from_at
   AND le.posted_at < :to_at
"""


def build(
    conn: Any,
    *,
    now: Any,
    since: Any,
    tenant_id: str | None = None,
    horizon_days: int = 90,
    customer_ids: Sequence[str] | None = None,
) -> dict[str, int]:
    """Rebuild the panel for every case with a decision at or after ``since``.

    Idempotent: cases are upserted on their key. ``now`` is passed in rather than
    read from the process clock so the caller -- a worker, or a test on a frozen
    transaction clock -- decides what "today" is. ``customer_ids`` narrows the
    rebuild to those borrowers; the worker never passes it.
    """
    from datetime import timedelta

    rows = conn.execute(
        text(_CASES),
        {
            "modes": list(PANEL_MODES),
            "since": since,
            "now": now,
            "tenant": tenant_id,
            "customers": list(customer_ids) if customer_ids is not None else None,
            "spell_trigger": SPELL_TRIGGER,
        },
    ).mappings().all()

    written = 0
    censored_cases = 0
    for row in rows:
        # A case every one of whose decisions our own executor cancelled has no
        # borrower outcome in it. It stays in the panel -- dropping it silently
        # is how a censoring rate becomes invisible -- and is marked so every
        # estimator can exclude it and publish the rate it excluded.
        censored = bool(row["cancelled"]) and row["cancelled"] == row["decisions"]
        if censored:
            censored_cases += 1
        reward = conn.execute(
            text(_REWARD),
            {
                "customer_id": row["customer_id"],
                "account_id": row["account_id"],
                "from_at": row["first_decision_at"],
                "to_at": row["first_decision_at"] + timedelta(days=horizon_days),
            },
        ).scalar()
        conn.execute(
            text(_UPSERT),
            {
                "id": _case_id(
                    str(row["tenant_id"]),
                    str(row["customer_id"]),
                    str(row["account_id"]),
                    str(row["trigger_kind"]),
                    str(row["spell_ref"]),
                ),
                "tenant_id": row["tenant_id"],
                "customer_id": row["customer_id"],
                "account_id": row["account_id"],
                "trigger_kind": row["trigger_kind"],
                "spell_ref": row["spell_ref"],
                "variant": row["variant"],
                "randomised_at": row["first_decision_at"],
                "decisions": row["decisions"],
                "enacted_decisions": row["enacted_decisions"],
                "reach_outcome": row["reach_outcome"],
                "cure_outcome": row["cure_outcome"],
                "reward_inr": float(reward or 0.0),
                "observed_days": row["observed_days"],
                "mature": bool(row["mature"]),
                "censored": censored,
                # A cancellation with no reason is still censoring. Logging
                # contract v1 predates `cancel_reason`, so the pre-cutover rows
                # -- which §15.2 W2 excludes from OPE permanently anyway -- carry
                # NULL. Naming that rather than dropping the flag keeps those
                # cases inside the published censoring rate instead of quietly
                # outside it.
                "censor_reason": (
                    (row["censor_reason"] or UNATTRIBUTED_CENSOR) if censored else None
                ),
                "first_decision_at": row["first_decision_at"],
                "last_decision_at": row["last_decision_at"],
                "label_definition_version": row["label_definition_version"],
                "logging_contract_version": row["logging_contract_version"],
                "modes": list(row["modes"] or []),
            },
        )
        written += 1

    logger.info(
        "analysis panel built cases=%s censored=%s since=%s",
        written,
        censored_cases,
        since,
    )
    return {"cases": written, "censored": censored_cases}


def clustering(conn: Any, *, tenant_id: str | None = None) -> dict[str, Any]:
    """Measured `m`, cluster counts and panel span — never assumed values.

    Returns the inputs §8.7 requires before any power figure or timeline may be
    quoted. The caller decides whether they clear a floor; this only measures.
    """
    row = conn.execute(
        text(
            """
            SELECT
              count(*)::int AS cases,
              count(DISTINCT customer_id)::int AS customers,
              count(DISTINCT customer_id) FILTER (
                WHERE variant = 'null_treatment'
              )::int AS control_clusters,
              count(DISTINCT customer_id) FILTER (
                WHERE variant IS DISTINCT FROM 'null_treatment'
              )::int AS treated_clusters,
              EXTRACT(EPOCH FROM (max(randomised_at) - min(randomised_at)))
                / 604800.0 AS weeks
            FROM analysis_panel
            WHERE (CAST(:tenant AS TEXT) IS NULL OR tenant_id = :tenant)
            """
        ),
        {"tenant": tenant_id},
    ).mappings().first()
    cases = int((row or {}).get("cases") or 0)
    customers = int((row or {}).get("customers") or 0)
    return {
        "cases": cases,
        "customers": customers,
        "casesPerCustomer": (cases / customers) if customers else 0.0,
        "controlClusters": int((row or {}).get("control_clusters") or 0),
        "treatedClusters": int((row or {}).get("treated_clusters") or 0),
        "weeks": float((row or {}).get("weeks") or 0.0),
    }
