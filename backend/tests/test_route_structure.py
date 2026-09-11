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
