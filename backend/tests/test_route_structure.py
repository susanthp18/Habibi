"""Routes live in routers/<domain>.py and every one declares its wire shape.

`main.py` was 6,089 lines with 341 routes and zero routers; 175 routes had no
`response_model`. That was a ratchet with two baseline files; it is a totality
now: zero untyped routes outside `_UNTYPED_BY_DESIGN`, zero `dict[str, Any]`
bodies on a route handler.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fastapi.routing import APIRoute

BACKEND = Path(__file__).resolve().parents[1]

# Routes that do not speak JSON, so a `response_model` would be a lie. Each
# declares its `response_class` instead. Not a ratchet: a route belongs here
# only while its wire format is not JSON.
_UNTYPED_BY_DESIGN = frozenset(
    {
        "GET /webhooks/whatsapp",  # Meta verification: echoes hub.challenge as text/plain
        "GET /webhook/whatsapp",  # same handler, the singular spelling Meta's UI sometimes sends
        "POST /twilio/voice/incoming",  # TwiML (application/xml) for Twilio
        "POST /twilio/voice/fallback",  # TwiML (application/xml) for Twilio
        "POST /twilio/voice/stream-status",  # Twilio status callback: 204, no body
        "POST /twilio/voice/call-status",  # Twilio status callback: 204, no body
        "POST /twilio/sms/status",  # Twilio status callback: 204, no body
        "GET /floor/copilot/{interaction_id}/stream",  # SSE (text/event-stream)
        "GET /interactions/{interaction_id}/export",  # JSON/Markdown file download
        "GET /agent-studio/skills/{skill_id}/export",  # zip download
        "GET /metrics",  # Prometheus text exposition
        "GET /pay/{token}",  # hosted checkout HTML
        "POST /tts/preview",  # audio bytes, vendor content type
        "GET /billing/export.csv",  # CSV download
        "DELETE /kb/faqs/{faq_id}",  # 204, no body
        "DELETE /billing/budgets/{budget_id}/rules/{rule_id}",  # 204, no body
    }
)


def _api_routes():
    import main as app_main

    return [r for r in app_main.app.routes if isinstance(r, APIRoute)]


def test_no_route_is_declared_in_main() -> None:
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    decorators = re.findall(r"^@app\.(get|post|put|patch|delete|websocket)\(", src, re.M)
    assert decorators == [], f"main.py still declares {len(decorators)} route(s)"


def test_every_router_module_is_included() -> None:
    import main as app_main

    included = {id(r) for r in app_main.app.routes}
    for path in sorted((BACKEND / "routers").glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = __import__(f"routers.{path.stem}", fromlist=["router"])
        for route in module.router.routes:
            assert id(route) in included, f"{path.name}: {getattr(route, 'path', route)} not included"


def test_response_model_totality() -> None:
    untyped = sorted(
        f"{sorted(r.methods)[0]} {r.path}"
        for r in _api_routes()
        if r.response_model is None
        and not r.path.startswith(("/docs", "/openapi", "/redoc"))
        and "text/event-stream" not in str(getattr(r, "response_class", ""))
    )
    untyped = [u for u in untyped if u not in _UNTYPED_BY_DESIGN]
    assert untyped == [], f"routes without a response_model: {untyped}"
    stale = sorted(
        u
        for u in _UNTYPED_BY_DESIGN
        if u not in {f"{sorted(r.methods)[0]} {r.path}" for r in _api_routes()}
    )
    assert stale == [], f"_UNTYPED_BY_DESIGN names routes that no longer exist: {stale}"


def _is_route(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in fn.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name):
            if call.value.id == "router" and call.attr in {"get", "post", "put", "patch", "delete"}:
                return True
    return False


def test_no_route_takes_an_untyped_dict_body() -> None:
    """`payload: dict[str, Any]` on a route is a body nobody validates.

    Helpers that take a parsed dict (`_twilio_signature_ok`, the agent-edit
    check) are not routes and are not counted.
    """
    hits: list[str] = []
    for path in sorted((BACKEND / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not _is_route(fn):
                continue
            for arg in fn.args.args + fn.args.kwonlyargs:
                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                if ann.replace(" ", "").startswith("dict[str,Any]"):
                    hits.append(f"{path.stem}.{fn.name}")
    assert hits == [], f"routes with an untyped dict body: {hits}"


# Request-model fields that carry a shape the request model cannot state, each
# with the owner that validates it. Not a ratchet: an entry belongs here only
# while that is true.
_OPAQUE_BY_DESIGN = {
    "a2a.A2aTaskRequest.input": "the skill's own input schema (agent_core.a2a)",
    "agent_studio.AgentCardCompileRequest.agentCard": "the compiler's G0 gate is the validator; a draft must stay savable",
    "agent_studio.AgentCardCompileRequest.flow": "flow_graph.parse_graph + validate_graph at compile",
    "agent_studio.AgentCardCompileRequest.persona": "compiled with the card; the compiler reports",
    "agent_studio.AgentCardCompileRequest.voice": "compiled with the card; the compiler reports",
    "agent_studio.AgentCardPatchRequest.agentCard": "a draft must stay savable; G0 judges it at compile",
    "agent_studio.PromptVersionCreateRequest.agentCard": "a draft must stay savable; G0 judges it at compile",
    "agent_studio.PromptVersionPatchRequest.agentCard": "a draft must stay savable; G0 judges it at compile",
    "agent_studio.SkillCreateRequest.frontmatter": "SKILL.md frontmatter; agent_core.skills validates",
    "agent_studio.SkillPatchRequest.frontmatter": "SKILL.md frontmatter; agent_core.skills validates",
    "agent_studio.SkillScriptRunRequest.payload": "the script's own input",
    "compliance.PolicyRuleDraftItemRequest.params": "shaped by kind; policy_rules.validate_params",
    "integrations.BankManifestIngestRequest.rows": "shaped by contract_code; the bank_boundary adapter validates",
    "routing.RoutingActionRequest.params": "shaped by the action key; db_routing resolves",
    "sandbox.SandboxRunCreateRequest.persona": "free text the tester typed, rendered into the prompt",
    "sandbox.TwinRunRequest.state": "the twin's own state",
    "telephony.TwilioOutboundCallRequest.custom": "passed through to the dialled bot's session",
    "telephony.VoiceSandboxStartRequest.persona": "free text the tester typed, rendered into the prompt",
    "telephony.VoiceSandboxStartRequest.tuning": "agent_core.tuning.normalize_tuning owns the shape and clamps it",
    "telephony.VoiceSandboxTuneRequest.tuning": "agent_core.tuning.normalize_tuning owns the shape and clamps it",
    "voice_catalog.TtsPreviewRequest.params": "provider-specific synthesis parameters",
}

_UNTYPED = re.compile(r"\bdict\b|\bAny\b")


def test_no_request_field_is_an_untyped_dict() -> None:
    """A `dict[str, Any]` on a request model is a body nobody validates.

    Every field of every `*Request` model in the schemas package is typed, or
    is listed in `_OPAQUE_BY_DESIGN` with the owner that validates it; the
    list is checked both ways so it cannot rot.
    """
    found: dict[str, str] = {}
    for path in sorted((BACKEND / "schemas").glob("*.py")):
        tree = ast.parse(path.read_bytes())
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef) or not cls.name.endswith("Request"):
                continue
            for st in cls.body:
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    ann = ast.unparse(st.annotation)
                    if _UNTYPED.search(ann):
                        found[f"{path.stem}.{cls.name}.{st.target.id}"] = ann
    untyped = sorted(set(found) - set(_OPAQUE_BY_DESIGN))
    assert untyped == [], f"request fields typed dict/Any without an owner: {untyped}"
    stale = sorted(set(_OPAQUE_BY_DESIGN) - set(found))
    assert stale == [], f"_OPAQUE_BY_DESIGN entries that are typed now: {stale}"


# --- registration order ------------------------------------------------------

_ORDER_SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "route_order.json"


def _route_order() -> list[str]:
    """``METHOD path`` in registration order. Order is behaviour: Starlette
    matches first-registered-first, so ``/x/published`` declared after
    ``/x/{id}`` is shadowed and answers 404 for a literal that exists."""
    out: list[str] = []
    for r in _api_routes():
        for method in sorted(r.methods or ()):
            out.append(f"{method} {r.path}")
    return out


def test_route_registration_order_is_pinned() -> None:
    """Five static-before-parameterised pairs live on definition order alone
    (CONFLICTS §C3); this is the ordered snapshot the router split was gated
    on and never got. Regenerate with UPDATE_SNAPSHOTS=1 and read the diff:
    a reordering is a behaviour change, not noise."""
    import json
    import os

    current = _route_order()
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not _ORDER_SNAPSHOT.exists():
        _ORDER_SNAPSHOT.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
    pinned = json.loads(_ORDER_SNAPSHOT.read_text(encoding="utf-8"))
    assert current == pinned, "route registration order changed; see the diff and regenerate deliberately"


def test_no_static_path_is_shadowed_by_a_parameter_declared_before_it() -> None:
    """The property the order snapshot protects, stated directly: for every
    literal path there is no earlier-registered route with the same method
    whose template matches it."""
    seen: list[tuple[str, re.Pattern[str]]] = []
    shadowed: list[str] = []
    for r in _api_routes():
        for method in sorted(r.methods or ()):
            if "{" not in r.path:
                for m, pattern in seen:
                    if m == method and pattern.fullmatch(r.path):
                        shadowed.append(f"{method} {r.path} (behind {pattern.pattern})")
            template = "^" + re.sub(r"\{[^}]+\}", r"[^/]+", re.escape(r.path).replace(r"\{", "{").replace(r"\}", "}")) + "$"
            seen.append((method, re.compile(template)))
    assert shadowed == [], shadowed
