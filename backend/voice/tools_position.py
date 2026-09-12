"""Voice tools -- the account position and the graph's own moves.

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

from voice.tool_state import (
    ToolBuildContext,
    _account_tail,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _close_probe_node = ctx._close_probe_node
    _node = ctx._node
    _require_customer = ctx._require_customer
    _spec = ctx._spec
    hub_node = ctx.hub_node
    session = ctx.session
    state = ctx.state


    # ----------------------------------------------------------------- reads

    # These four reads used to be hand-rolled Pipecat direct functions while
    # ALSO carrying a ToolSpec in agent_core.tools.catalog — the contract was
    # declared twice, which is precisely the drift the catalog exists to
    # prevent. They now render from the spec; cancel_on_interruption /
    # timeout_secs ride along on the ToolSpec (schema.py:147-150), and
    # tests/test_voice_tool_registry.py asserts the rendering matches.

    async def _get_account_position_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Return the verified caller's outstanding balance and due amounts.

        Must not be called before identity verification succeeds. This is a
        refresh of the injected CRM card, not the only way to learn the facts.
        """
        if not session.identity_verified:
            return {"error": "identity_not_verified"}, None
        payload: dict[str, Any] = {
            "customerName": state.customer_name,
            "outstandingInr": float(session.outstanding),
            "minimumDueInr": state.minimum_due,
            "dpd": state.dpd,
            # The hint changes after the first time. Left unconditional, it
            # reads as a standing order to recite the balance and the model
            # obeys it on every refresh — including the refreshes it makes to
            # answer something else entirely.
            "say": (
                "you have ALREADY told the caller these figures on this call — "
                "do not state them again unless they asked; use them only to "
                "answer what they actually said"
                if state.position_stated
                else "state outstanding and minimum due in one short sentence"
            ),
        }
        state.position_stated = True
        tail = _account_tail(session.account_id)
        if tail:
            payload["accountTail"] = tail
        return payload, None

    get_account_position = _spec("get_account_position", 
        _get_account_position_handler
    )

    async def _get_customer_context_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Compact CRM profile for the verified caller (name, risk, phones, open work)."""
        cid, err = _require_customer()
        if err:
            return err, None
        try:
            import db

            customer = await asyncio.to_thread(db.get_customer, cid)
        except Exception:
            logger.exception("get_customer_context failed")
            return {"error": "crm_read_failed"}, None
        if not customer:
            return {"error": "customer_not_found"}, None
        return {
            "ok": True,
            "name": customer.get("name"),
            "accountId": customer.get("accountId") or session.account_id,
            "outstandingInr": customer.get("outstanding"),
            "dpd": customer.get("dpd"),
            "risk": customer.get("risk"),
            "product": customer.get("product"),
            "preferredWindow": customer.get("preferredWindow"),
            "dnd": customer.get("dnd"),
            "say": "use only these CRM facts; do not invent balances",
        }, None

    get_customer_context = _spec("get_customer_context", 
        _get_customer_context_handler
    )

    async def _get_payment_history_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Recent ledger / payment entries for the verified account."""
        cid, err = _require_customer()
        if err:
            return err, None
        # normalize applies the spec default (limit=8) and drops unknown keys.
        args = CATALOG.normalize("get_payment_history", args)
        try:
            import db

            customer = await asyncio.to_thread(db.get_customer, cid)
        except Exception:
            logger.exception("get_payment_history failed")
            return {"error": "crm_read_failed"}, None
        if not customer:
            return {"error": "customer_not_found"}, None
        lim = max(1, min(int(args.get("limit") or 8), 20))
        ledger = list(customer.get("ledger") or [])[:lim]
        return {
            "ok": True,
            "accountId": customer.get("accountId") or session.account_id,
            "entries": ledger,
            "say": "summarize the last payments in one short sentence",
        }, None

    get_payment_history = _spec("get_payment_history", 
        _get_payment_history_handler
    )

    async def _get_emi_schedule_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Upcoming / recent EMI installments for the verified account."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("get_emi_schedule", args)
        try:
            import db

            customer = await asyncio.to_thread(db.get_customer, cid)
        except Exception:
            logger.exception("get_emi_schedule failed")
            return {"error": "crm_read_failed"}, None
        if not customer:
            return {"error": "customer_not_found"}, None
        lim = max(1, min(int(args.get("limit") or 6), 24))
        emi = list(customer.get("emi") or [])[:lim]
        return {
            "ok": True,
            "accountId": customer.get("accountId") or session.account_id,
            "installments": emi,
            "say": "state the next due installment briefly",
        }, None

    get_emi_schedule = _spec("get_emi_schedule", 
        _get_emi_schedule_handler
    )

    # ------------------------------------------------------------ node hops

    async def begin_negotiate(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Move to promise-to-pay negotiation when the caller wants a payment plan."""
        if not session.identity_verified:
            return {"error": "identity_not_verified"}, None
        return {"ok": True}, _node("negotiate_ptp")

    async def begin_dispute(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Move to dispute handling when the caller disputes the balance or charges."""
        if not session.identity_verified:
            return {"error": "identity_not_verified"}, None
        # A caller contesting a charge is not a caller to sell to.
        state.dispute_opened = True
        return {"ok": True}, _node("handle_dispute")

    async def begin_wrap_up(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Move to call wrap-up when the caller is done.

        Detours through the close probe exactly once first — asking "anything
        else?" is the last useful thing a service call does, and it is also the
        only moment an offer can be made without interrupting anything.
        """
        node = await _close_probe_node()
        if node is not None:
            return {"ok": True, "probing": True}, node
        return {"ok": True}, _node("wrap_up")

    async def return_to_position(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Return to the account-position hub after a side path."""
        if not session.identity_verified:
            return {"error": "identity_not_verified"}, None
        return {"ok": True}, _node(hub_node)

    return {
        "get_account_position": get_account_position,
        "get_customer_context": get_customer_context,
        "get_payment_history": get_payment_history,
        "get_emi_schedule": get_emi_schedule,
        "begin_negotiate": begin_negotiate,
        "begin_dispute": begin_dispute,
        "begin_wrap_up": begin_wrap_up,
        "return_to_position": return_to_position,
    }
