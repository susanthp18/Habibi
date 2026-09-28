"""Rerunning the Voice Studio seed changes nothing that already exists. No engine or DB."""

import pytest

import voice_studio_routing
from scripts import voice_studio_seed as seed


class FakeEngine:
    """Records writes; answers reads as if every starter asset already exists."""

    def __init__(self):
        self.writes: list[tuple[str, str]] = []
        self.tools = [{"name": s["name"], "tool_uuid": f"u-{s['name']}"} for s in seed.TOOLS] + [
            {"name": "transfer_to_human", "tool_uuid": "u-transfer_to_human"}
        ]

    def __call__(self, method, path, body=None):
        if method != "GET":
            self.writes.append((method, path))
            return {"id": 99, "tool_uuid": "new", "uuid": "new"}
        if path.startswith("/tools/"):
            return self.tools
        if path == "/credentials/":
            return [{"name": seed.CREDENTIAL_NAME, "credential_type": "bearer_token", "uuid": "cred"}]
        if path.startswith("/knowledge-base/documents"):
            return {"documents": []}
        if path == "/workflow/fetch?status=active":
            return [{"id": 4, "name": seed.AGENT_NAME}]
        if path == "/workflow/fetch/4":
            return {"workflow_definition": {"nodes": [
                {"type": "trigger", "data": {"trigger_path": "kept-path"}}]}}
        return {}


def test_existing_tools_credential_and_agent_are_left_untouched():
    engine = FakeEngine()
    credential = seed.ensure_credential(engine, "token")
    tools = seed.ensure_tools(engine, "http://hooks", credential)
    agent_id, trigger = seed.ensure_agent(engine, tools, "http://hooks", credential)
    assert engine.writes == []
    assert (agent_id, trigger) == (4, "kept-path")
    assert tools["verify_identity"] == "u-verify_identity"


def test_missing_bindings_are_reported_not_created(monkeypatch, capsys):
    assigned = []
    monkeypatch.setattr(seed, "missing_bindings", lambda wanted: ["whatsapp"])
    monkeypatch.setattr(voice_studio_routing, "assign", lambda *a, **k: assigned.append((a, k)))
    seed.bind(7, ["whatsapp"], "u-1", create=False)
    assert assigned == [] and "binding missing: whatsapp" in capsys.readouterr().out


def test_create_bindings_goes_through_the_audited_routing_path(monkeypatch):
    assigned = []
    monkeypatch.setattr(seed, "missing_bindings", lambda wanted: ["*", "whatsapp"])
    monkeypatch.setattr(voice_studio_routing, "assign", lambda wf, ch, **k: assigned.append((wf, ch, k["objective"])))
    seed.bind(7, ["*", "whatsapp"], "u-1", create=True)
    assert assigned == [(7, "outbound", "*"), (7, "whatsapp", "whatsapp")]


def test_a_tool_that_drifted_from_its_approved_shape_stops_the_seed(monkeypatch):
    engine = FakeEngine()
    monkeypatch.setattr(voice_studio_routing, "_check_tool",
                        lambda tool, cred: ["unapproved endpoint"] if tool["name"] == "promise_to_pay" else [])
    with pytest.raises(SystemExit, match="promise_to_pay: unapproved endpoint"):
        seed.validate_tools(engine, {t["name"]: t["tool_uuid"] for t in engine.tools}, "cred")


def test_outbound_edges_require_evidence_before_identity_or_success_close():
    tools = {spec["name"]: f"u-{spec['name']}" for spec in seed.TOOLS}
    tools["transfer_to_human"] = "u-transfer_to_human"
    definition = seed.build_definition(tools, "http://hooks", "cred", "trigger", [])
    edges = {(e["source"], e["target"]): e["data"] for e in definition["edges"]}

    assert edges["start", "verify"]["requires_user_turn"] is True
    assert edges["resolve", "end_done"]["requires_successful_action"] is True
    assert edges["resolve", "end_failed"]["allow_failed_action"] is True
