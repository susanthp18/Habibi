"""AgentStudio: PayInt's contact policy decides before the engine dials on its own.

Every outbound call is put to PayInt's ``/voice-studio/hooks/admit``. Calls
PayInt's dialler starts carry the attempt id it admitted them under
(``initial_context.attempt_id``); PayInt checks that attempt is real and for
this number. Every other call -- an engine campaign, the editor's "call
phone" -- meets the kill switch and the contact policy: DND, consent, the
calling window and frequency caps apply to it like to any contact, and a
number that is not a customer (or a configured test number) is refused.

Fails closed: if PayInt cannot be asked, the call is not placed.
Configured by ``PAYINT_ADMIT_URL`` and ``PAYINT_HOOK_TOKEN``; unset, nothing
is checked (a stock engine).
"""

import os
from typing import Optional

import httpx
from loguru import logger

from api.db import db_client


class DialRefused(RuntimeError):
    """PayInt did not admit the call."""


async def admit(to_number: str, workflow_run_id: Optional[int]) -> None:
    url = os.getenv("PAYINT_ADMIT_URL", "").strip()
    if not url:
        return
    context: dict = {}
    if workflow_run_id is not None:
        run = await db_client.get_workflow_run(workflow_run_id)
        context = dict((run.initial_context if run else None) or {})
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                url,
                json={
                    "to_number": to_number,
                    "workflow_run_id": workflow_run_id,
                    "workflow_id": context.get("workflow_id"),
                    "attempt_id": context.get("attempt_id"),
                },
                headers={"Authorization": f"Bearer {os.getenv('PAYINT_HOOK_TOKEN', '')}"},
            )
            resp.raise_for_status()
            decision = resp.json()
    except Exception as e:
        logger.error(f"PayInt admission unavailable; not dialling run {workflow_run_id}: {e}")
        raise DialRefused("PayInt contact policy could not be checked; the call was not placed") from e
    if not decision.get("admitted"):
        reason = decision.get("reason") or "refused"
        raise DialRefused(f"Blocked by PayInt contact policy: {reason}")
