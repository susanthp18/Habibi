"""Inbox: conversations, handoff, canned responses.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import kb_rate_limit

from fastapi import APIRouter
from fastapi import HTTPException, Query, Response
from schemas import (
    CannedResponseItem,
    ConversationListResponse,
    ConversationMessageCreateRequest,
    ConversationSuggestionsRefreshRequest,
    ConversationSuggestionsRefreshResponse,
    HandoffDisclosureRequest,
    HandoffQueueResponse,
    HandoffSessionResponse,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/handoff/queue", response_model=HandoffQueueResponse)
def get_handoff_queue(customerId: str | None = Query(default=None)):
    return db.list_handoff_queue(customer_id=customerId)

@router.get("/handoff/active", response_model=HandoffSessionResponse)
def get_handoff_active():
    session = db.get_active_handoff_session()
    if session is None:
        return Response(status_code=204)
    return session

@router.get("/handoff/{interaction_id}", response_model=HandoffSessionResponse)
def get_handoff_by_id(interaction_id: str):
    return _handle_write(db.get_handoff_session, interaction_id)

@router.post("/handoff/{interaction_id}/claim", response_model=HandoffSessionResponse)
def claim_handoff(interaction_id: str):
    return _handle_write(db.claim_handoff, interaction_id)

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

@router.get("/conversations", response_model=list[ConversationListResponse])
def list_conversations(updatedAfter: str | None = None):
    try:
        return db.list_conversations(updated_after=updatedAfter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/conversations/{conversation_id}", response_model=ConversationListResponse)
def get_conversation(conversation_id: str):
    conversation = db.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation_not_found")
    return conversation

@router.post("/conversations/{conversation_id}/takeover", response_model=ConversationListResponse)
def takeover_conversation(conversation_id: str):
    return _handle_write(db.takeover_conversation, conversation_id)

@router.post("/conversations/{conversation_id}/return-to-bot", response_model=ConversationListResponse)
def return_conversation_to_bot(conversation_id: str):
    return _handle_write(db.return_conversation_to_bot, conversation_id)

@router.post("/conversations/{conversation_id}/messages", response_model=ConversationListResponse)
def send_conversation_message(conversation_id: str, payload: ConversationMessageCreateRequest):
    return _handle_write(
        db.send_conversation_message,
        conversation_id,
        payload.model_dump(),
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
    """Debounced Inbox consumer: shared retrieve() → ai_response_suggestions chips."""
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
    except kb_rate_limit.RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("inbox rag refresh failed conversation=%s", conversation_id)
        raise HTTPException(status_code=502, detail="inbox_rag_failed") from exc

