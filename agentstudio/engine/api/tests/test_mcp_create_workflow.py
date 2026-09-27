from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.mcp_server.tools.create_workflow import create_workflow


@pytest.mark.asyncio
async def test_create_workflow_rejects_duplicate_api_triggers():
    user = MagicMock()
    user.id = 1
    user.selected_organization_id = 1
    payload = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startCall",
                "position": {"x": 0, "y": 0},
                "data": {"name": "Start", "prompt": "Greet."},
            },
            {
                "id": "trigger-1",
                "type": "trigger",
                "position": {"x": 0, "y": 200},
                "data": {"name": "Trigger A", "trigger_path": "support_west"},
            },
            {
                "id": "trigger-2",
                "type": "trigger",
                "position": {"x": 0, "y": 400},
                "data": {"name": "Trigger B", "trigger_path": "support_east"},
            },
        ],
        "edges": [],
    }

    with (
        patch(
            "api.mcp_server.tools.create_workflow.authenticate_mcp_request",
            AsyncMock(return_value=user),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.parse_code",
            AsyncMock(
                return_value={
                    "ok": True,
                    "workflowName": "duplicate-trigger-test",
                    "workflow": payload,
                }
            ),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.reconcile_positions",
            return_value=payload,
        ),
        patch(
            "api.mcp_server.tools.create_workflow.db_client.create_workflow_draft",
            AsyncMock(),
        ) as create_mock,
    ):
        result = await create_workflow(code="ignored")

    assert result["created"] is False
    assert result["error_code"] == "graph_validation"
    assert "at most one API Trigger" in result["error"]
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_workflow_makes_a_draft_and_activates_no_trigger():
    """An assistant authors; a person publishes. Nothing created here may be
    live: no published version, and no trigger row a caller could hit."""
    user = MagicMock()
    user.id = 1
    user.selected_organization_id = 1
    payload = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startCall",
                "position": {"x": 0, "y": 0},
                "data": {"name": "Start", "prompt": "Greet."},
            },
            {
                "id": "trigger-1",
                "type": "trigger",
                "position": {"x": 0, "y": 200},
                "data": {"name": "Trigger", "trigger_path": "draft_only_path"},
            },
        ],
        "edges": [],
    }
    workflow = MagicMock(id=7, status="active")
    workflow.name = "draft-only"
    with (
        patch(
            "api.mcp_server.tools.create_workflow.authenticate_mcp_request",
            AsyncMock(return_value=user),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.parse_code",
            AsyncMock(return_value={"ok": True, "workflowName": "draft-only", "workflow": payload}),
        ),
        patch("api.mcp_server.tools.create_workflow.reconcile_positions", return_value=payload),
        patch(
            "api.mcp_server.tools.create_workflow.validate_workflow_tool_name_collisions",
            AsyncMock(return_value=[]),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.db_client.assert_trigger_paths_available",
            AsyncMock(),
        ),
        patch(
            "api.mcp_server.tools.create_workflow.db_client.create_workflow_draft",
            AsyncMock(return_value=workflow),
        ) as draft_mock,
        patch(
            "api.mcp_server.tools.create_workflow.db_client.create_workflow",
            AsyncMock(),
        ) as publish_mock,
        patch(
            "api.mcp_server.tools.create_workflow.db_client.sync_triggers_for_workflow",
            AsyncMock(),
        ) as sync_mock,
        patch("api.mcp_server.tools.create_workflow.capture_event"),
    ):
        result = await create_workflow(code="ignored")

    assert result["created"] is True
    assert result["version_status"] == "draft"
    draft_mock.assert_awaited_once()
    publish_mock.assert_not_awaited()
    sync_mock.assert_not_awaited()
