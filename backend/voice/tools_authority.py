"""Voice tools -- authority evaluation and goodwill.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _announce = ctx._announce
    _require_customer = ctx._require_customer
    _schedule_context_refresh = ctx._schedule_context_refresh
    _spec = ctx._spec
    session = ctx.session
    state = ctx.state


    async def _evaluate_authority_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("evaluate_authority", args)
        try:
            result = await asyncio.to_thread(
                domain.evaluate_authority,
                customer_id=cid,
                fee_type=str(args.get("fee_type") or "late_fee"),
                asked_amount=args.get("asked_amount"),
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                identity_verified=True,
            )
        except Exception:
            logger.exception("evaluate_authority failed")
            return {
                "verdict": "escalate",
                "suppressed": True,
                "apply": False,
                "say": "do not quote a waiver or settlement figure; escalate",
            }, None
        payload = dict(result.data or {})
        cap = payload.get("approvedAmount") or payload.get("capAmount")
        try:
            state.authority_cap = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            state.authority_cap = None

        # The mission's authority profile, applied on top. The matrix decides
        # what policy permits for this account; the profile is a second and
        # narrower bound this particular call was sent out under — a pre-due
        # courtesy call has no business conceding what a broken-promise chase
        # might. It can only ever lower, which is what stops a card authoring
        # itself more discretion than the matrix would grant.
        #
        # The in-memory payload is what the Mouth quotes. apply_goodwill re-reads
        # approved_amount from the row, so the ceiling has to land there too
        # or a pre-due courtesy Mission posts the un-narrowed matrix figure.
        _mission = session.extra.get("mission")
        _profile = (_mission or {}).get("authorityProfile") if isinstance(_mission, dict) else None
        if _profile and state.authority_cap is not None:
            from agent_core.authority import config as _authority_config
            from agent_core.authority import decisions as _authority_decisions

            ceiling = _authority_config.profile_ceiling(_profile)
            if ceiling is not None and ceiling < state.authority_cap:
                decision_id = payload.get("decisionId")
                if decision_id:
                    try:
                        await asyncio.to_thread(
                            _authority_decisions.bind_ceiling,
                            str(decision_id),
                            ceiling=ceiling,
                            profile=_profile,
                        )
                    except Exception:
                        logger.exception(
                            "authority mission ceiling persist failed for %s",
                            decision_id,
                        )
                        return {
                            "verdict": "escalate",
                            "suppressed": True,
                            "apply": False,
                            "say": (
                                "do not quote a waiver or settlement figure; escalate"
                            ),
                        }, None
                logger.info(
                    "authority narrowed by mission profile %s: %s -> %s",
                    _profile,
                    state.authority_cap,
                    ceiling,
                )
                state.authority_cap = ceiling
                payload["approvedAmount"] = ceiling
                payload["capAmount"] = ceiling
                payload["narrowedBy"] = _profile
                if ceiling <= 0:
                    payload["verdict"] = "escalate"
                    payload["say"] = (
                        "do not quote any waiver or settlement figure on this "
                        "call; offer to have a colleague call them back"
                    )
        if state.authority_cap is not None:
            session.extra["max_waiver_inr"] = state.authority_cap
        if result.spoken_summary:
            payload.setdefault("say", result.spoken_summary)
        await _announce(result, "evaluate_authority", inject_delta=False)
        # Snapshot lands on the CRM card so later turns cannot invent a larger figure.
        _schedule_context_refresh("evaluate_authority")
        return payload, None

    evaluate_authority = _spec("evaluate_authority", _evaluate_authority_handler)

    async def _apply_goodwill_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("apply_goodwill", args)
        # The decision id comes from the model's own call, never from a slot
        # on the session: under run_in_parallel two evaluate_authority calls
        # overwrote one slot, and the second waiver posted against the first
        # verdict. The spec marks it required; the model has it because it
        # was the one that received it.
        decision_id = str(args.get("decision_id") or "")
        if not decision_id:
            return {
                "error": "missing_decision",
                "say": "call evaluate_authority before applying goodwill",
            }, None
        try:
            result = await asyncio.to_thread(
                domain.apply_goodwill,
                decision_id=decision_id,
                amount=args.get("amount"),
            )
        except Exception:
            logger.exception("apply_goodwill failed")
            return {
                "error": "crm_write_failed",
                "say": "apologise and offer a specialist callback",
            }, None
        if not result.ok:
            return {
                "error": result.error or "apply_failed",
                "say": result.spoken_summary
                or "do not confirm a waiver; offer a specialist callback",
            }, None
        await _announce(result, "apply_goodwill", inject_delta=False)
        _schedule_context_refresh("apply_goodwill")
        return {
            "ok": True,
            **(result.data or {}),
            "say": result.spoken_summary or "confirm the goodwill reversal briefly",
        }, None

    apply_goodwill = _spec("apply_goodwill", _apply_goodwill_handler)

    return {
        "evaluate_authority": evaluate_authority,
        "apply_goodwill": apply_goodwill,
    }
