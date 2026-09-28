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


@pytest.mark.asyncio
async def test_tracing_failure_does_not_skip_payint_notice(monkeypatch):
    run = SimpleNamespace(
        workflow=object(),
        definition=SimpleNamespace(workflow_json={}, id=1),
        campaign_id=None,
    )
    monkeypatch.setattr(run_integrations.db_client, "get_workflow_run_with_context",
                        AsyncMock(return_value=(run, 11)))
    monkeypatch.setattr(run_integrations.db_client, "get_configuration_value",
                        AsyncMock(return_value={"host": "https://example.test"}))
    notice = AsyncMock()
    monkeypatch.setattr(run_integrations, "_notify_payint", notice)
    monkeypatch.setattr(run_integrations, "register_org_langfuse_credentials",
                        lambda **kwargs: (_ for _ in ()).throw(AttributeError("exporter failed")))

    await run_integrations.run_integrations_post_workflow_run({}, 42)

    notice.assert_awaited_once_with(run, 11, 42)
