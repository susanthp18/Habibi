"""Orchestration — the only entry point callers need.

    features → matrix → log

Two properties this function must hold, because it runs on the audio path of a
live phone call:

* **It never raises.** Any failure degrades to escalate, logged.
* **``approved_amount`` is always inside the cap, or ``None``.** The model
  never invents a figure this module did not emit.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from agent_core.authority import config, decisions, talk
from agent_core.authority.features import (
    FEE_LATE,
    FEE_TYPES,
    SCHEMA_VERSION,
    AccountAuthority,
    FeatureProvider,
    build_features,
)
from agent_core.authority.matrix import (
    ENGINE_ERROR,
    ENGINE_OFF,
    UNKNOWN_FEE,
    VERDICT_ESCALATE,
    MatrixDecision,
    decide,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthorityResult:
    """What the tool layer and the screens consume."""

    verdict: str = VERDICT_ESCALATE
    approved_amount: float | None = None
    cap_amount: float | None = None
    reason: str | None = ENGINE_ERROR
    reason_codes: tuple[str, ...] = ()
    talk_track: str = ""
    fee_type: str = FEE_LATE
    asked_amount: float | None = None
    decision_id: str | None = None
    mode: str = config.MODE_SHADOW
    suppressed: bool = True
    latency_ms: int = 0
    customer_id: str | None = None
    account_id: str | None = None
    packet: dict[str, Any] | None = None

    @property
    def actionable(self) -> bool:
        """True only when live goodwill may actually post on this call."""
        return (
            not self.suppressed
            and self.mode == config.MODE_LIVE
            and self.approved_amount is not None
            and self.verdict != VERDICT_ESCALATE
        )

    def to_payload(self) -> dict[str, Any]:
        """Model- and UI-facing shape. Scores stay out; the rupee cap stays in."""
        return {
            "verdict": self.verdict,
            "approvedAmount": self.approved_amount,
            "capAmount": self.cap_amount,
            "reason": self.reason,
            "reasonCodes": list(self.reason_codes),
            "talkTrack": self.talk_track,
            "feeType": self.fee_type,
            "askedAmount": self.asked_amount,
            "decisionId": self.decision_id,
            "mode": self.mode,
            "suppressed": self.suppressed,
            "actionable": self.actionable,
            "packet": self.packet,
            "latencyMs": self.latency_ms,
        }

    def to_tool_payload(self) -> dict[str, Any]:
        """What the model is allowed to see.

        Shadow still returns the verdict so a supervisor UI can show it, but
        the spoken instruction is escalate-shaped: the bot must not apply.
        """
        payload = self.to_payload()
        if self.mode != config.MODE_LIVE or not self.actionable:
            payload["say"] = (
                self.talk_track
                if self.verdict == VERDICT_ESCALATE
                else (
                    "Do not approve or quote a waiver amount on this call. "
                    "Log a fee_waiver dispute and offer a specialist callback. "
                    + (self.talk_track or "")
                )
            )
            payload["apply"] = False
        else:
            payload["say"] = self.talk_track
            payload["apply"] = True
        return payload


def recommend_authority(
    *,
    customer_id: str,
    account_id: str | None = None,
    interaction_id: str | None = None,
    fee_type: str = FEE_LATE,
    asked_amount: float | None = None,
    identity_verified: bool = True,
    conn: Any | None = None,
    provider: FeatureProvider | None = None,
    force_mode: str | None = None,
    features: AccountAuthority | None = None,
) -> AuthorityResult:
    """Decide the allowed move. Never raises."""
    started = time.perf_counter()
    mode = (force_mode or config.mode()).strip().lower()
    kind = (fee_type or FEE_LATE).strip().lower() or FEE_LATE

    if mode == config.MODE_OFF:
        return AuthorityResult(
            verdict=VERDICT_ESCALATE,
            reason=ENGINE_OFF,
            reason_codes=(ENGINE_OFF,),
            talk_track=talk.escalate_line(ENGINE_OFF, fee_type=kind),
            fee_type=kind,
            asked_amount=asked_amount,
            mode=mode,
            suppressed=True,
            customer_id=customer_id,
            account_id=account_id,
        )

    try:
        return _recommend(
            customer_id=customer_id,
            account_id=account_id,
            interaction_id=interaction_id,
            fee_type=kind,
            asked_amount=asked_amount,
            identity_verified=identity_verified,
            conn=conn,
            provider=provider,
            mode=mode,
            features=features,
            started=started,
        )
    except Exception:
        logger.exception("authority recommendation failed for customer=%s", customer_id)
        return AuthorityResult(
            verdict=VERDICT_ESCALATE,
            reason=ENGINE_ERROR,
            reason_codes=(ENGINE_ERROR,),
            talk_track=talk.escalate_line(ENGINE_ERROR, fee_type=kind),
            fee_type=kind,
            asked_amount=asked_amount,
            mode=mode,
            suppressed=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            customer_id=customer_id,
            account_id=account_id,
        )


def _recommend(
    *,
    customer_id: str,
    account_id: str | None,
    interaction_id: str | None,
    fee_type: str,
    asked_amount: float | None,
    identity_verified: bool,
    conn: Any | None,
    provider: FeatureProvider | None,
    mode: str,
    features: AccountAuthority | None,
    started: float,
) -> AuthorityResult:
    import db

    kind = fee_type if fee_type in FEE_TYPES else FEE_LATE
    if fee_type not in FEE_TYPES:
        matrix = decide(
            AccountAuthority(
                customer_id=customer_id,
                tenant_id=db.current_tenant(),
                identity_verified=identity_verified,
            ),
            fee_type=fee_type,
            asked_amount=asked_amount,
        )
        # Still log unknown fee types so we can see the model inventing them.
        return _finish(
            matrix=matrix,
            features=features
            or AccountAuthority(customer_id=customer_id, tenant_id=db.current_tenant()),
            customer_id=customer_id,
            account_id=account_id,
            interaction_id=interaction_id,
            fee_type=FEE_LATE,
            asked_amount=asked_amount,
            mode=mode,
            conn=conn,
            started=started,
        )

    if features is None:
        if conn is not None:
            loaded = build_features(
                conn, customer_id=customer_id, account_id=account_id, provider=provider
            )
        else:
            with db.engine.connect() as owned:
                loaded = build_features(
                    owned,
                    customer_id=customer_id,
                    account_id=account_id,
                    provider=provider,
                )
        features = loaded

    if not identity_verified:
        from dataclasses import replace

        features = replace(features, identity_verified=False)

    matrix = decide(features, fee_type=kind, asked_amount=asked_amount)
    return _finish(
        matrix=matrix,
        features=features,
        customer_id=customer_id,
        account_id=features.account_id or account_id,
        interaction_id=interaction_id,
        fee_type=kind,
        asked_amount=asked_amount,
        mode=mode,
        conn=conn,
        started=started,
    )


def _finish(
    *,
    matrix: MatrixDecision,
    features: AccountAuthority,
    customer_id: str,
    account_id: str | None,
    interaction_id: str | None,
    fee_type: str,
    asked_amount: float | None,
    mode: str,
    conn: Any | None,
    started: float,
) -> AuthorityResult:
    import db

    latency_ms = int((time.perf_counter() - started) * 1000)
    track = talk.talk_track(matrix, fee_type=fee_type)
    pkt = talk.packet(
        matrix,
        fee_type=fee_type,
        asked_amount=asked_amount,
        customer_id=customer_id,
    )
    decision_id = decisions.record(
        conn=conn,
        tenant_id=features.tenant_id or db.current_tenant(),
        customer_id=customer_id,
        account_id=account_id,
        interaction_id=interaction_id,
        fee_type=fee_type,
        asked_amount=asked_amount,
        mode=mode,
        feature_schema_version=SCHEMA_VERSION,
        features=features.to_log(),
        verdict=matrix.verdict,
        approved_amount=matrix.approved_amount,
        cap_amount=matrix.cap_amount,
        reason=matrix.reason,
        reason_codes=matrix.reason_codes,
        talk_track=track,
        latency_ms=latency_ms,
    )
    suppressed = mode != config.MODE_LIVE or matrix.verdict == VERDICT_ESCALATE
    return AuthorityResult(
        verdict=matrix.verdict,
        approved_amount=matrix.approved_amount,
        cap_amount=matrix.cap_amount,
        reason=matrix.reason,
        reason_codes=matrix.reason_codes,
        talk_track=track,
        fee_type=fee_type,
        asked_amount=asked_amount,
        decision_id=decision_id,
        mode=mode,
        suppressed=suppressed,
        latency_ms=latency_ms,
        customer_id=customer_id,
        account_id=account_id,
        packet=pkt,
    )
