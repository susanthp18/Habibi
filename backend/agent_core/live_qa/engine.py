"""Orchestration — the only entry point callers need.

    facts → checks → log

Runs on the audio path of a live phone call, so:

* **It never raises.** Any failure degrades to pass / no action.
* **The LLM does not barge.** Findings are deterministic. An LLM may later
  draft empathy scores; it cannot introduce a check or take over audio.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from agent_core.live_qa import config, decisions
from agent_core.live_qa.checks import (
    ACTION_BARGE,
    ACTION_NONE,
    SCHEMA_VERSION,
    VERDICT_PASS,
    Finding,
    TurnFacts,
    evaluate_turn,
    facts_to_log,
    verdict_of,
    worst_action,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveQaResult:
    verdict: str = VERDICT_PASS
    recommended_action: str = ACTION_NONE
    reason: str | None = None
    reason_codes: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    decision_id: str | None = None
    mode: str = config.MODE_SHADOW
    auto_barge: bool = False
    latency_ms: int = 0
    flags: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "recommendedAction": self.recommended_action,
            "reason": self.reason,
            "reasonCodes": list(self.reason_codes),
            "findings": [f.to_log() for f in self.findings],
            "decisionId": self.decision_id,
            "mode": self.mode,
            "autoBarge": self.auto_barge,
            "flags": list(self.flags),
            "latencyMs": self.latency_ms,
        }


def evaluate_live_qa(
    facts: TurnFacts,
    *,
    customer_id: str | None = None,
    account_id: str | None = None,
    interaction_id: str | None = None,
    tenant_id: str | None = None,
    conn: Any | None = None,
    force_mode: str | None = None,
) -> LiveQaResult:
    """Score one turn. Never raises."""
    started = time.perf_counter()
    mode = (force_mode or config.mode()).strip().lower()
    try:
        return _evaluate(
            facts=facts,
            customer_id=customer_id,
            account_id=account_id,
            interaction_id=interaction_id,
            tenant_id=tenant_id,
            conn=conn,
            mode=mode,
            started=started,
        )
    except Exception:
        logger.exception("live_qa evaluation failed for ix=%s", interaction_id)
        return LiveQaResult(
            mode=mode,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _evaluate(
    *,
    facts: TurnFacts,
    customer_id: str | None,
    account_id: str | None,
    interaction_id: str | None,
    tenant_id: str | None,
    conn: Any | None,
    mode: str,
    started: float,
) -> LiveQaResult:
    findings = evaluate_turn(facts)
    action = worst_action(findings, channel=facts.channel)
    verdict = verdict_of(findings)
    codes = tuple(f.check_id for f in findings if not f.passed)
    reason = next((f.reason for f in findings if not f.passed), None)
    flags = tuple(f.flag for f in findings if not f.passed)
    latency_ms = int((time.perf_counter() - started) * 1000)

    # Off still scores — evidence is not optional — but never auto-barges and
    # does not write a row. Shadow writes. Live writes and may auto-barge.
    decision_id = None
    if mode != config.MODE_OFF and (findings or action != ACTION_NONE):
        try:
            import db

            decision_id = decisions.record(
                conn=conn,
                tenant_id=tenant_id or db.current_tenant(),
                customer_id=customer_id,
                account_id=account_id,
                interaction_id=interaction_id,
                mode=mode,
                feature_schema_version=SCHEMA_VERSION,
                features=facts_to_log(facts),
                verdict=verdict,
                recommended_action=action,
                reason=reason,
                reason_codes=codes,
                findings=[f.to_log() for f in findings],
                latency_ms=latency_ms,
            )
        except Exception:
            logger.exception("live_qa log failed for ix=%s", interaction_id)

    auto = (
        mode == config.MODE_LIVE
        and action == ACTION_BARGE
        and any(c in config.AUTO_BARGE_CHECKS for c in codes)
    )
    return LiveQaResult(
        verdict=verdict,
        recommended_action=action,
        reason=reason,
        reason_codes=codes,
        findings=findings,
        decision_id=decision_id,
        mode=mode,
        auto_barge=auto,
        latency_ms=latency_ms,
        flags=flags,
    )
