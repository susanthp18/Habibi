"""WS7: routes live in routers/<domain>.py and every one declares its wire shape.

`main.py` was 6,089 lines with 341 routes and zero routers; 175 routes had no
`response_model` and the count crept (+50 since the baseline) because the
guard stopped at the literal prefix `/agent-studio`. The counts here are the
ratchet: they may go down, never up.
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
    }
)


def _baseline(name: str) -> list[str]:
    """One entry per line; `#` lines are comments. The file is the ratchet."""
    lines = (BACKEND / "tests" / name).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


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
    baseline = _baseline("route_shape_baseline.txt")
    new = sorted(set(untyped) - set(baseline))
    assert not new, f"routes added without a response_model: {new}"
    closed = sorted(set(baseline) - set(untyped))
    assert not closed, f"routes now typed -- remove them from route_shape_baseline.txt: {closed}"


def test_dict_bodies_do_not_grow() -> None:
    """`payload: dict[str, Any]` on a write is a body nobody validates."""
    hits: list[str] = []
    for path in sorted((BACKEND / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for arg in fn.args.args + fn.args.kwonlyargs:
                ann = ast.unparse(arg.annotation) if arg.annotation else ""
                if ann.replace(" ", "").startswith("dict[str,Any]"):
                    hits.append(f"{path.stem}.{fn.name}")
    baseline = _baseline("dict_body_baseline.txt")
    new = sorted(set(hits) - set(baseline))
    assert not new, f"routes added with an untyped dict body: {new}"
    closed = sorted(set(baseline) - set(hits))
    assert not closed, f"bodies now typed -- remove them from dict_body_baseline.txt: {closed}"
