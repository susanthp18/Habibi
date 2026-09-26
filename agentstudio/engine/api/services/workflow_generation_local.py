"""Self-hosted "create agent from a description".

AgentStudio replacement for the vendor's hosted workflow generator. The
organization's own LLM drafts the graph from the registered node specs; the
draft is validated exactly like a saved workflow (ReactFlowDTO + WorkflowGraph)
and repaired once from the validation errors before it is returned in the
shape the hosted service used: {"name", "workflow_definition"}.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pipecat.processors.aggregators.llm_context import LLMContext
from pydantic import ValidationError

from api.services.configuration.ai_model_configuration import (
    get_effective_ai_model_configuration_for_workflow,
)
from api.services.gen_ai.json_parser import parse_llm_json
from api.services.pipecat.service_factory import create_llm_service_with_model_override
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.node_specs import get_spec
from api.services.workflow.workflow_graph import WorkflowGraph

_NODE_TYPES = ("startCall", "agentNode", "endCall", "globalNode")


def _spec_brief() -> list[dict]:
    brief = []
    for name in _NODE_TYPES:
        spec = get_spec(name)
        if spec is None:
            continue
        brief.append(
            {
                "type": spec.name,
                "description": spec.description,
                "hint": spec.llm_hint,
                "examples": [e.data for e in spec.examples],
                "graph_constraints": spec.graph_constraints.model_dump(mode="json")
                if spec.graph_constraints
                else None,
            }
        )
    return brief


_SYSTEM = """You design voice-agent call flows as JSON.
Return ONLY a JSON object: {{"name": str, "workflow_definition": {{"nodes": [...], "edges": [...]}}}}.
Node: {{"id": str, "type": one of {types}, "position": {{"x": number, "y": number}},
       "data": {{"name": str, "prompt": str, ...fields from the examples}}}}.
Edge: {{"id": str, "source": node id, "target": node id,
       "data": {{"label": short str, "condition": when the conversation should move on}}}}.
Rules: exactly one startCall; at least one endCall; every node except startCall and
globalNode is reachable; endCall nodes have no outgoing edges; at most one globalNode
(persona and shared rules, no edges). Prompts are instructions to the agent, spoken
style, short sentences. Node specs:
{specs}"""


async def _infer(llm, messages: list[dict], system: str) -> str:
    context = LLMContext()
    context.set_messages(messages)
    return await llm.run_inference(context, system_instruction=system) or ""


def _problems(definition: dict) -> list[str]:
    try:
        WorkflowGraph(ReactFlowDTO.model_validate(definition))
    except ValidationError as exc:
        return [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()][:20]
    except ValueError as exc:
        detail = exc.args[0] if exc.args else exc
        return [str(d) for d in detail][:20] if isinstance(detail, list) else [str(detail)]
    return []


async def generate(
    *, organization_id: int, call_type: str, use_case: str, activity_description: str
) -> dict:
    config = await get_effective_ai_model_configuration_for_workflow(
        organization_id=organization_id, workflow_configurations={}
    )
    if config.llm is None:
        raise HTTPException(status_code=400, detail="Configure an LLM under Models first.")
    llm = create_llm_service_with_model_override(
        config, None, usage_context="workflow_generation"
    )
    system = _SYSTEM.format(types=list(_NODE_TYPES), specs=json.dumps(_spec_brief(), indent=1))
    messages = [
        {
            "role": "user",
            "content": (
                f"Call direction: {call_type}\nUse case: {use_case}\n"
                f"What the agent should do: {activity_description}"
            ),
        }
    ]

    for attempt in range(2):
        raw = await _infer(llm, messages, system)
        try:
            draft = parse_llm_json(raw)
        except Exception:
            draft = {}
        definition = draft.get("workflow_definition") or {}
        problems = _problems(definition) if definition else ["No workflow_definition returned."]
        if not problems:
            return {"name": draft.get("name") or use_case, "workflow_definition": definition}
        messages += [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": "Fix these problems and return the full JSON again:\n- "
                + "\n- ".join(problems),
            },
        ]
    raise HTTPException(
        status_code=422,
        detail="Could not draft a valid agent from that description; try adding more detail.",
    )
