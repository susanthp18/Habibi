"""AgentStudio: every finished run is posted to PayInt as a durable delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.tasks import run_integrations


@pytest.mark.asyncio
async def test_notice_is_a_durable_delivery_with_the_hooks_credential(monkeypatch):
    monkeypatch.setenv("PAYINT_RUN_COMPLETED_URL", "http://api:8000/voice-studio/hooks/run-completed")
    creds = [SimpleNamespace(name="Other", credential_uuid="c-0"),
             SimpleNamespace(name="PayInt hooks", credential_uuid="c-1")]
    monkeypatch.setattr(run_integrations.db_client, "get_credentials_for_organization",
                        AsyncMock(return_value=creds))
    create = AsyncMock(return_value=(SimpleNamespace(id=7), True))
    monkeypatch.setattr(run_integrations.db_client, "create_webhook_delivery", create)
    enqueue = AsyncMock()
    monkeypatch.setattr("api.tasks.arq.enqueue_job", enqueue)

    await run_integrations._notify_payint(SimpleNamespace(workflow_id=3), 11, 42)

    kwargs = create.await_args.kwargs
    assert kwargs["payload"] == {"workflow_run_id": 42, "workflow_id": 3}
    assert kwargs["credential_uuid"] == "c-1"
    assert kwargs["webhook_node_id"] == run_integrations.PAYINT_DELIVERY_NODE_ID
    enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_url_or_no_credential_sends_nothing(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(run_integrations.db_client, "create_webhook_delivery", create)
    monkeypatch.delenv("PAYINT_RUN_COMPLETED_URL", raising=False)
    await run_integrations._notify_payint(SimpleNamespace(workflow_id=3), 11, 42)
    monkeypatch.setenv("PAYINT_RUN_COMPLETED_URL", "http://x/run-completed")
    monkeypatch.setattr(run_integrations.db_client, "get_credentials_for_organization", AsyncMock(return_value=[]))
    await run_integrations._notify_payint(SimpleNamespace(workflow_id=3), 11, 42)
    create.assert_not_awaited()
