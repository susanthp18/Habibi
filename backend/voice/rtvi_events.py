"""BigBound RTVI server→client message contract.

Native RTVI already reports transcripts, metrics, speaking state and function
calls. What it cannot know is our *domain*: which CRM row a tool just created,
which KB chunks grounded an answer, which Flows node we are on. Those ride
``RTVIServerMessageFrame`` (docs: rtvi-processor § Custom Messaging — a
high-priority SystemFrame that stays ordered and survives interruptions).

Contract (server → client), mirrored by ``useSandboxLiveCall`` on the frontend:

===================== ==========================================
``crm.entity``        ``{entity, id, deepLink, tool, summary}``
``rag.hits``          ``{query, chunkIds, snapshotId, topScore}``
``flow.node``         ``{name, previous}``
``session.lifecycle`` ``{phase, reason}``
``handoff.status``    ``{mode, state, reason, assignee?, team?, conversationId?}``
``context.card``      ``{card}`` — sandbox debug only
===================== ==========================================

Emission is strictly best-effort: a Sandbox Inspector that misses a chip is a
cosmetic problem, a voice call that dies because the data channel hiccuped is
not. Every helper swallows its own errors.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RtviEmitter:
    """Thin wrapper over ``RTVIProcessor.send_server_message``.

    Constructed before the worker exists (tools are built first), so the RTVI
    processor is attached later via :meth:`bind`. Calls before binding are
    dropped silently — that is the correct behaviour for a non-sandbox
    transport where no client is listening.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._rtvi: Any = None
        self._enabled = enabled

    def bind(self, rtvi: Any) -> None:
        self._rtvi = rtvi

    @property
    def bound(self) -> bool:
        return self._rtvi is not None and self._enabled

    async def send(self, type_: str, payload: dict[str, Any] | None = None) -> None:
        if not self.bound:
            return
        try:
            await self._rtvi.send_server_message({"type": type_, **(payload or {})})
        except Exception:
            # Never let UI telemetry break the call.
            logger.debug("rtvi send_server_message failed (%s)", type_, exc_info=True)

    # ------------------------------------------------------------- helpers

    async def crm_entity(
        self,
        *,
        entity: str,
        entity_id: str | None,
        deep_link: str | None = None,
        tool: str | None = None,
        summary: str | None = None,
    ) -> None:
        """A CRM row was created — the Inspector renders a deep-link chip."""
        await self.send(
            "crm.entity",
            {
                "entity": entity,
                "id": entity_id,
                "deepLink": deep_link,
                "tool": tool,
                "summary": summary,
            },
        )

    async def rag_hits(
        self,
        *,
        query: str,
        chunk_ids: list[str] | None = None,
        snapshot_id: str | None = None,
        top_score: float | None = None,
        source: str = "tool",
    ) -> None:
        """KB retrieval happened — feeds the Live Retrieval tab."""
        await self.send(
            "rag.hits",
            {
                "query": query,
                "chunkIds": chunk_ids or [],
                "snapshotId": snapshot_id,
                "topScore": top_score,
                "source": source,
            },
        )

    async def flow_node(self, *, name: str, previous: str | None = None) -> None:
        """Flows transitioned — shows the caller's position in the script."""
        await self.send("flow.node", {"name": name, "previous": previous})

    async def lifecycle(self, *, phase: str, reason: str | None = None) -> None:
        """connect / verified / idle / escalate / ending / end."""
        await self.send("session.lifecycle", {"phase": phase, "reason": reason})

    async def handoff_status(
        self,
        *,
        mode: str,
        state: str,
        reason: str | None = None,
        assignee: str | None = None,
        team: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Handoff state. ``mode`` is ``callback_queue`` until warm transfer ships."""
        payload: dict[str, Any] = {"mode": mode, "state": state, "reason": reason}
        if assignee:
            payload["assignee"] = assignee
        if team:
            payload["team"] = team
        if conversation_id:
            payload["conversationId"] = conversation_id
        await self.send("handoff.status", payload)

    async def context_card(self, card: str) -> None:
        """Sandbox-only CallContext debug dump."""
        await self.send("context.card", {"card": card})
