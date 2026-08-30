"""The mission's time budget, enforced rather than suggested.

``CardObjective.max_duration_sec`` reached the model as a line in the briefing —
*"keep this call under about four minutes"* — and nothing else. A budget the
model is asked to respect is a budget, and a budget nothing checks is a wish.
The failure mode is not dramatic: a borrower who wants to talk and an agent
happy to oblige produce a twelve-minute call about a ₹4,800 instalment, and the
only place it shows up is the bill.

Two stages, and the gap between them is the point
--------------------------------------------------
At the budget, the agent is *told* to converge — a developer message, injected
between turns, that asks it to close or offer a callback. It keeps the turn it
is in, keeps the sentence it is saying, and keeps whatever the borrower was
part-way through telling it.

At the hard stop it ends the call. That is the backstop for an agent that
cannot converge, not the mechanism — a call that reaches it is a QA finding.

Cutting a borrower off mid-sentence to honour a number would be worse than the
overrun it prevents, which is why there is a margin at all and why the first
stage is a request rather than a hangup.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

#: Grace between "please converge" and "the call ends now". Long enough for a
#: wrap-up turn and a goodbye; short enough that it is not a second budget.
HARD_STOP_MARGIN_SEC = 60

_NUDGE = (
    "You are at this call's time budget. Bring it to a close now: confirm what "
    "was agreed in one short sentence, or — if nothing is agreed — offer to "
    "have a colleague call them back at a time that suits them. Do not open a "
    "new topic and do not restate the account position."
)


def budget_for(session: Any) -> int:
    """Seconds this mission may run, or 0 when it carries no budget.

    Inbound calls have none, deliberately: the caller rang us and gets as long
    as they need.
    """
    extra = getattr(session, "extra", None) or {}
    try:
        return max(0, int(extra.get("max_duration_sec") or 0))
    except (TypeError, ValueError):
        return 0


async def watch(
    session: Any,
    *,
    nudge: Callable[[str], Awaitable[None]] | None,
    end_call: Callable[[], Awaitable[None]] | None,
    budget_sec: int | None = None,
) -> None:
    """Sleep to the budget, ask the agent to converge, then stop the call.

    Cancelled with the session — a call that ends on its own never reaches
    either stage, which is the ordinary case and costs one sleeping task.
    """
    budget = budget_sec if budget_sec is not None else budget_for(session)
    if budget <= 0:
        return
    try:
        await asyncio.sleep(budget)
        if getattr(session, "extra", {}).get("ending"):
            return
        logger.info(
            "mission budget reached · session=%s · %ss — asking the agent to close",
            getattr(session, "session_id", "?"),
            budget,
        )
        session.extra["budget_nudged"] = True
        if nudge is not None:
            try:
                await nudge(_NUDGE)
            except Exception:
                logger.exception("budget nudge failed")

        await asyncio.sleep(HARD_STOP_MARGIN_SEC)
        if getattr(session, "extra", {}).get("ending"):
            return
        # A call that gets here could not converge when asked. Ending it is the
        # backstop; the finding is that the agent needed one.
        logger.warning(
            "mission budget exceeded · session=%s · ending the call after %ss",
            getattr(session, "session_id", "?"),
            budget + HARD_STOP_MARGIN_SEC,
        )
        session.extra["budget_exceeded"] = True
        if end_call is not None:
            try:
                await end_call()
            except Exception:
                logger.exception("budget hard stop failed")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("budget watchdog failed")
