"""Inbox: conversations, handoff, canned responses.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import db

from fastapi import APIRouter
from fastapi import Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from schemas import (
    CannedResponseItem,
    ConversationCountsResponse,
    ConversationMessageCreateRequest,
    ConversationResponse,
    ConversationSuggestionsRefreshRequest,
    ConversationSuggestionsRefreshResponse,
    ConversationSummaryResponse,
    ConversationTakeoverRequest,
    HandoffClaimRequest,
    HandoffDisclosureRequest,
    HandoffQueueResponse,
    HandoffSessionResponse,
    InboxView,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/handoff/queue", response_model=HandoffQueueResponse)
def get_handoff_queue(
    customerId: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=500),
):
    return db.list_handoff_queue(customer_id=customerId, search=q, limit=limit)


@router.get("/handoff/{interaction_id}", response_model=HandoffSessionResponse)
def get_handoff_by_id(interaction_id: str):
    return _handle_write(db.get_handoff_session, interaction_id)

# text/event-stream by design: the copilot's pack, then its whisper tokens, as
# SSE, for whoever may open the case (its holder, or a supervisor watching).
# Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/handoff/{interaction_id}/copilot/stream", response_class=StreamingResponse)
def stream_handoff_copilot(interaction_id: str):
    from agent_core.copilot import iter_events

    _handle_write(db.assert_handoff_readable, interaction_id)
    events = iter_events(interaction_id)
    first = next(events, None)
    if first is None or first.get("type") == "error":
        raise HTTPException(status_code=404, detail="interaction_not_found")

    def _sse() -> Any:
        yield f"event: {first['type']}\ndata: {json.dumps(first, default=str)}\n\n"
        for event in events:
            name = str(event.get("type") or "message")
            yield f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.post("/handoff/{interaction_id}/claim", response_model=HandoffSessionResponse)
def claim_handoff(interaction_id: str, payload: HandoffClaimRequest | None = None):
    return _handle_write(
        db.claim_handoff,
        interaction_id,
        payload.model_dump(exclude_unset=True) if payload else None,
    )

@router.post("/handoff/{interaction_id}/disclosures", response_model=HandoffSessionResponse)
def post_handoff_disclosure(interaction_id: str, payload: HandoffDisclosureRequest):
    return _handle_write(
        db.record_handoff_disclosure,
        interaction_id,
        payload.model_dump(exclude_none=True),
    )

@router.post("/handoff/{interaction_id}/suggestions/{suggestion_id}/accept", response_model=HandoffSessionResponse)
def accept_handoff_suggestion(interaction_id: str, suggestion_id: str):
    return _handle_write(db.accept_handoff_suggestion, interaction_id, suggestion_id)

@router.get("/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations(
    updatedAfter: str | None = None,
    customerId: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    view: InboxView | None = None,
    beforeAt: str | None = None,
    beforeId: str | None = Query(default=None, max_length=200),
):
    try:
        return db.list_conversations(
            updated_after=updatedAfter,
            customer_id=customerId,
            q=q,
            view=view,
            before_at=beforeAt,
            before_id=beforeId,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/conversations/counts", response_model=ConversationCountsResponse)
def get_conversation_counts():
    return db.conversation_counts()

@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str):
    conversation = db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return conversation

@router.post("/conversations/{conversation_id}/takeover", response_model=ConversationResponse)
def takeover_conversation(conversation_id: str, payload: ConversationTakeoverRequest | None = None):
    return _handle_write(
        db.takeover_conversation,
        conversation_id,
        payload.model_dump(exclude_unset=True) if payload else None,
    )

@router.post("/conversations/{conversation_id}/return-to-bot", response_model=ConversationResponse)
def return_conversation_to_bot(conversation_id: str):
    return _handle_write(db.return_conversation_to_bot, conversation_id)

@router.post("/conversations/{conversation_id}/messages", response_model=ConversationResponse)
def send_conversation_message(
    conversation_id: str,
    payload: ConversationMessageCreateRequest,
    idempotency_key: str | None = Header(default=None),
):
    return _handle_write(
        db.send_conversation_message,
        conversation_id,
        payload.model_dump(),
        idempotency_key,
    )

@router.get("/canned-responses", response_model=list[CannedResponseItem])
def list_canned_responses():
    return db.list_canned_responses()

@router.post(
    "/conversations/{conversation_id}/suggestions/refresh",
    response_model=ConversationSuggestionsRefreshResponse,
)
def refresh_conversation_suggestions(
    conversation_id: str,
    payload: ConversationSuggestionsRefreshRequest | None = None,
):
    """Debounced Inbox consumer: Voice Studio knowledge base → ai_response_suggestions chips."""
    body = payload or ConversationSuggestionsRefreshRequest()
    try:
        return db.refresh_conversation_suggestions(
            conversation_id,
            top_k=body.topK,
            include_draft_answer=body.includeDraftAnswer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("inbox rag refresh failed conversation=%s", conversation_id)
        raise HTTPException(status_code=502, detail="inbox_rag_failed") from exc

