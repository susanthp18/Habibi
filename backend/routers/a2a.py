"""Agent-to-agent: partner certificates, the well-known card, task intake.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException, Query, Request
from schemas import (
    A2aAgentCardResponse,
    A2aPartnerResponse,
    A2aPartnerUpsertRequest,
    A2aTaskRequest,
    A2aTaskResponse,
    A2aTaskSignalRequest,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/.well-known/agent-card.json", response_model=A2aAgentCardResponse)
def a2a_well_known_card(request: Request, botId: str | None = Query(default=None)):
    from agent_core import a2a as a2a_mod

    bot_id = botId or db.DEFAULT_BOT_ID
    try:
        a2a_mod.require_partner(
            {k.lower(): v for k, v in request.headers.items()},
            bot_id=bot_id,
            client_host=request.client.host if request.client else None,
        )
        return a2a_mod.agent_card_document(bot_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/a2a", response_model=A2aTaskResponse, response_model_exclude_unset=True)
def a2a_protocol_task(request: Request, payload: A2aTaskRequest):
    from agent_core import a2a as a2a_mod

    headers = {k.lower(): v for k, v in request.headers.items()}
    bot_id = str(payload.botId or db.DEFAULT_BOT_ID)
    try:
        partner = a2a_mod.require_partner(
            headers, bot_id=bot_id, client_host=request.client.host if request.client else None
        )
        dn = a2a_mod.client_cert_dn(headers)
        inner = payload.input or {}
        if payload.inputRequired and "inputRequired" not in inner:
            inner = {**inner, "inputRequired": True}
        return a2a_mod.create_task(
            partner=partner,
            skill_id=str(payload.skillId or ""),
            payload=inner or payload.model_dump(exclude_none=True),
            bot_id=bot_id,
            cert_dn=dn,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/a2a/partners", response_model=list[A2aPartnerResponse])
def list_a2a_partners():
    from agent_core import a2a as a2a_mod

    return a2a_mod.list_partners()

@router.post("/a2a/partners", response_model=A2aPartnerResponse)
def upsert_a2a_partner(payload: A2aPartnerUpsertRequest):
    from agent_core import a2a as a2a_mod

    return _handle_write(a2a_mod.upsert_partner, payload.model_dump(exclude_none=True))

@router.get("/a2a/tasks", response_model=list[A2aTaskResponse])
def list_a2a_tasks(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core import a2a as a2a_mod

    return a2a_mod.list_tasks(limit=limit)

@router.post("/a2a/tasks/{task_id}/signal", response_model=A2aTaskResponse)
def signal_a2a_task(task_id: str, payload: A2aTaskSignalRequest | None = None):
    from agent_core import a2a as a2a_mod

    name = (payload.name if payload else "") or "approve"
    return _handle_write(a2a_mod.signal_task, task_id, name)

