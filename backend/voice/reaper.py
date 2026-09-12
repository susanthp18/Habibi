"""End the calls whose voice worker stopped heartbeating."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from agent_core.clock import utc_now as _now

logger = logging.getLogger(__name__)


def reap_stale(engine: Any, older_than: timedelta) -> list[dict[str, str]]:
    """End the calls whose worker stopped heartbeating.

    A voice process killed mid-call left its session ``live`` and its
    interaction ``active`` forever: the floor showed a call that was not
    happening, the fleet gate counted a slot that was free, and the campaign
    never got its attempt back. ``last_heartbeat_at`` was written on every
    turn and read by nobody. Same threshold as the dialer's stale sweep --
    longer than any plausible silence inside a live call -- and the same
    verdict: ``abandoned``/``failed``, never deleted, because a call we lost
    track of is evidence.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                UPDATE voice_sessions
                   SET status = 'failed', ended_at = now(), updated_at = now()
                 WHERE status IN ('starting', 'live')
                   AND COALESCE(last_heartbeat_at, started_at, created_at) < :cutoff
                RETURNING id, interaction_id
                """
            ),
            {"cutoff": _now() - older_than},
        ).mappings().all()
        reaped = [{"sessionId": r["id"], "interactionId": r["interaction_id"]} for r in rows]
        for r in reaped:
            conn.execute(
                text(
                    """
                    UPDATE interactions
                       SET status = 'abandoned', ended_at = now(), updated_at = now()
                     WHERE id = :ix AND status = 'active'
                    """
                ),
                {"ix": r["interactionId"]},
            )
            # Free the dial slot the attempt still held; the state machine
            # never walks backwards, so a closed attempt stays closed.
            from outbound import TERMINAL

            conn.execute(
                text(
                    """
                    UPDATE call_attempts
                       SET state = 'failed',
                           provider_error = COALESCE(provider_error, 'voice_session_lost'),
                           ended_at = now(), updated_at = now()
                     WHERE interaction_id = :ix AND NOT (state = ANY(:terminal))
                    """
                ),
                {"ix": r["interactionId"], "terminal": list(TERMINAL)},
            )
    if reaped:
        logger.warning("voice: reaped %s stale session(s): %s", len(reaped), [r["sessionId"] for r in reaped])
    return reaped
