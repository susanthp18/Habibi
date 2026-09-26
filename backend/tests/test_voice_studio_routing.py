"""Routing preflight is a policy gate; no live calls or DB writes."""

import voice_studio_routing as routing
import voice_studio
from scripts.voice_studio_seed import build_definition
import pytest


def _definition(*, channel="inbound"):
    start = {"id": "start", "type": "startCall", "data": {"pre_call_fetch_mode": "inbound" if channel == "inbound" else "none", "prompt": "outbound"}}
    return {"nodes": [
        {"id": "global", "type": "globalNode", "data": {"prompt": f"{channel} customer help"}},
        start,
        {"id": "general", "type": "agentNode", "data": {"name": "General information"}},
        {"id": "verify", "type": "agentNode", "data": {"tool_uuids": ["verify"]}},
        {"id": "help", "type": "agentNode", "data": {"tool_uuids": ["position"]}},
        {"id": "trigger", "type": "trigger", "data": {"enabled": True, "trigger_path": "safe-path"}},
    ], "edges": [
        {"source": "start", "target": "general"}, {"source": "start", "target": "verify"},
        {"source": "general", "target": "verify"}, {"source": "verify", "target": "help"},
    ]}


def _tools(monkeypatch):
    monkeypatch.setattr(routing, "_check_tool", lambda tool, credential: [])
    revision = {"state": "approved", "policy": {"channels": ["inbound"]}}
    return {"verify": {"name": "verify_identity", "_revision": revision},
            "position": {"name": "account_position", "_revision": revision}}


def test_inbound_requires_intent_path_before_account_help(monkeypatch):
    tools = _tools(monkeypatch)
    definition = _definition()
    assert routing.validate_definition(definition, channel="inbound", active_tools=tools, credential_uuid="credential")["ok"]
    definition["edges"].append({"source": "start", "target": "help"})
    checked = routing.validate_definition(definition, channel="inbound", active_tools=tools, credential_uuid="credential")
    assert not checked["ok"]
    assert any("before identity verification" in error for error in checked["errors"])


def test_inbound_rejects_outbound_shared_flow(monkeypatch):
    tools = _tools(monkeypatch)
    definition = _definition()
    definition["nodes"] = [node for node in definition["nodes"] if node["id"] != "general"]
    checked = routing.validate_definition(definition, channel="inbound", active_tools=tools, credential_uuid="credential")
    assert not checked["ok"]
    assert any("intent choice" in error for error in checked["errors"])


def test_trigger_comes_from_published_definition(monkeypatch):
    monkeypatch.setattr(routing, "_published", lambda _id: ({}, {"workflow_json": _definition(channel="outbound")}))
    assert routing.outbound_trigger_path(7) == "safe-path"


def test_business_tool_destination_and_context_are_checked(monkeypatch):
    monkeypatch.setattr(routing, "env_str", lambda _name, default: default)
    tool = {"name": "promise_to_pay", "definition": {"type": "http_api", "config": {
        "method": "POST", "url": "https://unapproved.example/tools/promise_to_pay",
        "credential_uuid": "wrong", "parameters": [], "preset_parameters": [],
    }}}
    errors = routing._check_tool(tool, "approved")
    assert any("approved POST endpoint" in error for error in errors)
    assert any("credential" in error for error in errors)
    assert any("amount" in error for error in errors)
    assert any("workflow_run_id" in error for error in errors)


def test_whatsapp_lookup_does_not_use_outbound_default(monkeypatch):
    import db

    monkeypatch.setattr(db, "current_tenant", lambda: "tenant")

    class _Result:
        def mappings(self):
            return self

        def first(self):
            return None

    class _Connection:
        def execute(self, _query, params):
            assert params["o"] == "whatsapp"
            assert params["fallback"] == "whatsapp"
            return _Result()

    assert voice_studio.agent_for(_Connection(), "whatsapp", allow_default=False) is None


def test_repeat_callback_returns_existing_booking(monkeypatch):
    import db
    from datetime import datetime, timezone
    from agent_core.tools import domain

    booked = datetime(2026, 9, 27, 6, 0, tzinfo=timezone.utc)

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _query, _params):
            return self

        def scalar_one_or_none(self):
            return booked

    class _Engine:
        def connect(self):
            return _Connection()

    monkeypatch.setattr(db, "engine", _Engine())
    monkeypatch.setattr(domain, "request_callback", lambda **_kw: (_ for _ in ()).throw(AssertionError("duplicate write")))
    result = voice_studio._tool_request_callback({"customer_id": "customer"}, {"when": "2026-09-27T06:00:00Z"}, "interaction")
    assert result["ok"] is False
    assert result["error"] == "callback_already_booked"
    assert result["existingTime"] == booked.isoformat()


@pytest.mark.parametrize("channel", ["inbound", "outbound", "whatsapp"])
def test_starter_workflows_pass_channel_preflight_without_calls(monkeypatch, channel):
    monkeypatch.setattr(routing, "_check_tool", lambda tool, credential: [])
    names = list(routing.APPROVED_ARGUMENTS)
    definition = build_definition({name: name for name in names}, "http://hooks", "credential", "trigger", [], channel)
    active_tools = {name: {"name": name, "_revision": {"state": "approved", "policy": {"channels": [channel]}}} for name in names}
    checked = routing.validate_definition(definition, channel=channel,
                                          active_tools=active_tools, credential_uuid="credential")
    assert checked["ok"], checked["errors"]
    failure_edge = next(edge for edge in definition["edges"] if edge["target"] == "end_failed")
    assert failure_edge["data"]["allow_failed_action"] is True
    assert "not recorded" in next(node for node in definition["nodes"] if node["id"] == "end_failed")["data"]["prompt"]
    assert checked["warnings"] == []


def test_missing_failure_close_path_is_visible_without_disabling_existing_route(monkeypatch):
    monkeypatch.setattr(routing, "_check_tool", lambda tool, credential: [])
    names = list(routing.APPROVED_ARGUMENTS)
    definition = build_definition({name: name for name in names}, "http://hooks", "credential", "trigger", [], "outbound")
    definition["edges"] = [edge for edge in definition["edges"] if edge["target"] != "end_failed"]
    checked = routing.validate_definition(definition, channel="outbound",
                                          active_tools={name: {"name": name, "_revision": {"state": "approved", "policy": {"channels": ["outbound"]}}} for name in names},
                                          credential_uuid="credential")
    assert checked["ok"]
    assert any("failure close path" in warning for warning in checked["warnings"])


def test_inbound_provider_refusal_restores_original_mapping(monkeypatch):
    monkeypatch.setattr(routing, "preflight", lambda _id, _channel: {
        "ok": True, "definitionId": 4, "name": "Inbound help", "triggerPath": None,
    })
    writes = []

    def engine_call(method, _path, json=None):
        if method == "GET":
            return {"is_active": True, "inbound_workflow_id": 1}
        writes.append(json)
        return {"provider_sync": {"ok": len(writes) != 1}}

    monkeypatch.setattr(routing.voice_studio, "engine_call", engine_call)
    with pytest.raises(RuntimeError, match="previous mapping was restored"):
        routing.assign(2, "inbound", config_id=3, phone_id=5)
    assert writes == [{"inbound_workflow_id": 2}, {"inbound_workflow_id": 1}]


def test_inbound_audit_failure_restores_original_mapping(monkeypatch):
    import db

    monkeypatch.setattr(routing, "preflight", lambda _id, _channel: {
        "ok": True, "definitionId": 4, "name": "Inbound help", "triggerPath": None,
    })
    monkeypatch.setattr(routing, "_audit_assignment", lambda *_args: (_ for _ in ()).throw(RuntimeError("audit unavailable")))

    class _Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Engine:
        def begin(self):
            return _Transaction()

    monkeypatch.setattr(db, "engine", _Engine())
    writes = []

    def engine_call(method, _path, json=None):
        if method == "GET":
            return {"is_active": True, "inbound_workflow_id": 1}
        writes.append(json)
        return {"provider_sync": {"ok": True}}

    monkeypatch.setattr(routing.voice_studio, "engine_call", engine_call)
    with pytest.raises(RuntimeError, match="audit failed"):
        routing.assign(2, "inbound", config_id=3, phone_id=5)
    assert writes == [{"inbound_workflow_id": 2}, {"inbound_workflow_id": 1}]


def test_uncertain_inbound_update_retries_original_mapping(monkeypatch):
    monkeypatch.setattr(routing, "preflight", lambda _id, _channel: {
        "ok": True, "definitionId": 4, "name": "Inbound help", "triggerPath": None,
    })
    writes = []

    def engine_call(method, _path, json=None):
        if method == "GET":
            return {"is_active": True, "inbound_workflow_id": 1}
        writes.append(json)
        if len(writes) == 1:
            raise TimeoutError("response lost")
        return {"provider_sync": {"ok": True}}

    monkeypatch.setattr(routing.voice_studio, "engine_call", engine_call)
    with pytest.raises(RuntimeError, match="previous mapping was restored"):
        routing.assign(2, "inbound", config_id=3, phone_id=5)
    assert writes == [{"inbound_workflow_id": 2}, {"inbound_workflow_id": 1}]
