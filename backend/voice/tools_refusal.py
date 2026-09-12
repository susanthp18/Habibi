"""Voice tools -- the caller declines to verify, or is not the account holder.

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
from agent_core.tools.pipecat_compat import flows_tool_options

from voice import persist

from voice.tool_state import (
    ToolBuildContext,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _node = ctx._node
    bot_id = ctx.bot_id
    session = ctx.session
    state = ctx.state


    @flows_tool_options(cancel_on_interruption=False)
    async def refuse_verification(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Caller refuses to verify identity, or says they are not the account holder.

        After two refusals, or if they are a third party, end politely.
        """
        state.verify_refusals += 1
        ix = session.interaction_id
        if state.verify_refusals >= 2:
            if ix:
                await asyncio.to_thread(
                    persist.record_handoff,
                    interaction_id=ix,
                    reason="verification_failed",
                    bot_id=bot_id,
                )
            return (
                {
                    "ok": False,
                    "refused": True,
                    "say": "explain verification is required and end politely",
                },
                _node("terminate_politely"),
            )
        return (
            {
                "ok": False,
                "refused": True,
                "remaining_refusals": 1,
                "say": (
                    "briefly explain why verification is required for account "
                    "privacy, then ask again for last 4 mobile digits"
                ),
            },
            None,
        )

    @flows_tool_options(cancel_on_interruption=False)
    async def not_account_holder(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Caller says they are not the account holder / third party."""
        session.extra["third_party"] = True
        # The other half of right-party contact. An attempt that reached a
        # human who is not the borrower is fully paid for and worth zero, and
        # until the two were told apart every connect looked like a success.
        _attempt = session.extra.get("attempt_id")
        if _attempt:

            def _mark_wrong_party() -> None:
                import db as _db
                import outbound as _outbound

                with _db.engine.begin() as conn:
                    _outbound.mark(conn, str(_attempt), right_party=False, answered_by="human")

            try:
                await asyncio.to_thread(_mark_wrong_party)
            except Exception:
                logger.debug("wrong-party mark failed", exc_info=True)
        ix = session.interaction_id
        if ix:
            await asyncio.to_thread(
                persist.record_handoff,
                interaction_id=ix,
                reason="verification_failed",
                bot_id=bot_id,
            )
        # Inbound and outbound end differently, and the difference matters.
        # Inbound: a stranger rang *us* about someone else's account, so
        # "I can only discuss this with the holder" is the whole answer.
        # Outbound: we rang *them*, and this person now knows a bank called
        # about a specific individual. Saying we can only discuss "the account"
        # has already confirmed there is one. The third_party node exists to say
        # materially less than that.
        outbound_leg = str(session.extra.get("objective") or "").strip() != ""
        landing = _node("third_party") if outbound_leg else None
        return (
            {
                "ok": True,
                "thirdParty": True,
                "say": (
                    "do not confirm or deny that an account exists; say only that "
                    "it is a personal matter for the account holder"
                    if outbound_leg
                    else "explain you can only discuss the account with the holder; "
                    "suggest the holder call from their registered number"
                ),
            },
            landing or _node("terminate_politely"),
        )

    return {
        "refuse_verification": refuse_verification,
        "not_account_holder": not_account_holder,
    }
