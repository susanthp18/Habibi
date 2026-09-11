"""WP-042: ``response_model`` on /agent-studio must match what already ships.

FastAPI filters undeclared fields. A model that is a subset of the live dict
drops keys from the wire and the frontend types still compile. These tests
compare the HTTP body to the mapper output, key for key.
"""

from __future__ import annotations

import json

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse as StarletteStreamingResponse

import db
import schemas
from agent_core.cards.compile import CompileReport
from agent_core.cards.templates import templates
from agent_core.skills.persist import get_skill, list_skills
from agent_core.skills.scripts import SCRIPT_NAMES, run_script


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def _assert_same_shape(raw, served, *, path: str = "$") -> None:
    if isinstance(raw, dict):
        assert isinstance(served, dict), f"{path} expected object"
        dropped = set(raw) - set(served)
        added = set(served) - set(raw)
        assert not dropped, f"{path} dropped {sorted(dropped)}"
        assert not added, f"{path} added {sorted(added)}"
        for key in raw:
            _assert_same_shape(raw[key], served[key], path=f"{path}.{key}")
        return
    if isinstance(raw, list):
        assert isinstance(served, list), f"{path} expected array"
        assert len(raw) == len(served), f"{path} length {len(served)} != {len(raw)}"
        for i, (left, right) in enumerate(zip(raw, served)):
            _assert_same_shape(left, right, path=f"{path}[{i}]")
        return
    assert served == raw, f"{path}: {served!r} != {raw!r}"


def _studio_routes():
    import main as app_main

    return [
        route
        for route in app_main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/agent-studio")
    ]


def test_every_agent_studio_route_declares_a_response_shape() -> None:
    routes = _studio_routes()
    # 30 since the entry-bindings writer (GET/PUT/DELETE /agent-studio/entry-bindings).
    # The count is a guard: bump it only after checking the new route declares
    # a shape.
    assert len(routes) == 30
    for route in routes:
        if route.path.endswith("/export"):
            assert issubclass(route.response_class, StarletteStreamingResponse), route.path
            continue
        assert route.response_model is not None, route.path


def test_skills_scripts_is_still_declared_before_skill_id() -> None:
    """FastAPI matches in definition order. Reverse this pair and the picker 404s."""
    paths = [route.path for route in _studio_routes()]
    scripts = paths.index("/agent-studio/skills/scripts")
    by_id = paths.index("/agent-studio/skills/{skill_id}")
    assert scripts < by_id


def test_live_mapper_output_validates(db_tx) -> None:
    cards = db.list_agent_studio_cards(include_archived=True)
    assert cards
    for card in cards:
        schemas.AgentStudioCardResponse.model_validate(card)

    one = db.get_agent_studio_card(cards[0]["botId"])
    assert one is not None
    schemas.AgentStudioCardResponse.model_validate(one)

    for row in templates():
        schemas.AgentStudioTemplateResponse.model_validate(row)

    log = db.agent_change_log(limit=50)
    schemas.AgentStudioChangeLogResponse.model_validate(log)

    report = db.compile_agent_studio_card(cards[0]["botId"])
    CompileReport.model_validate(report)

    skills = list_skills()
    assert skills
    for skill in skills:
        schemas.AgentStudioSkillSummaryResponse.model_validate(skill)

    detail = get_skill(skills[0]["id"])
    assert detail is not None
    schemas.AgentStudioSkillResponse.model_validate(detail)

    for name in SCRIPT_NAMES:
        schemas.AgentStudioScriptRunResponse.model_validate(run_script(name, {}))
    schemas.AgentStudioScriptRunResponse.model_validate(run_script("no-such-script", {}))


def test_http_bodies_keep_every_mapper_key(api_headers) -> None:
    import main as app_main

    with TestClient(app_main.app, headers=api_headers) as client:
        cards = client.get("/agent-studio/cards")
        assert cards.status_code == 200, cards.text
        _assert_same_shape(_jsonable(db.list_agent_studio_cards()), cards.json())

        bot_id = cards.json()[0]["botId"]
        one = client.get(f"/agent-studio/cards/{bot_id}")
        assert one.status_code == 200, one.text
        _assert_same_shape(_jsonable(db.get_agent_studio_card(bot_id)), one.json())

        tmpl = client.get("/agent-studio/templates")
        assert tmpl.status_code == 200, tmpl.text
        _assert_same_shape(_jsonable(templates()), tmpl.json())

        graph = client.get(f"/agent-studio/cards/{bot_id}/graph")
        assert graph.status_code == 200, graph.text
        body = graph.json()
        assert "from" in body["edges"][0] if body["edges"] else True
        assert all("from_" not in edge for edge in body["edges"])

        log = client.get("/agent-studio/change-log?limit=20")
        assert log.status_code == 200, log.text
        _assert_same_shape(_jsonable(db.agent_change_log(limit=20)), log.json())

        compiled = client.post(f"/agent-studio/cards/{bot_id}/compile", json={})
        assert compiled.status_code == 200, compiled.text
        _assert_same_shape(_jsonable(db.compile_agent_studio_card(bot_id)), compiled.json())

        skills = client.get("/agent-studio/skills")
        assert skills.status_code == 200, skills.text
        _assert_same_shape(_jsonable(list_skills()), skills.json())

        slug = skills.json()[0]["slug"]
        skill = client.get(f"/agent-studio/skills/{slug}")
        assert skill.status_code == 200, skill.text
        _assert_same_shape(_jsonable(get_skill(slug)), skill.json())

        scripts = client.get("/agent-studio/skills/scripts")
        assert scripts.status_code == 200, scripts.text
        assert scripts.json() == [{"name": n} for n in SCRIPT_NAMES]

        export = client.get(f"/agent-studio/skills/{slug}/export")
        assert export.status_code == 200, export.text
        assert export.headers["content-type"].startswith("application/zip")

        remaining = client.post(
            "/agent-studio/skills/run-script",
            json={"name": "emi_remaining", "payload": {"outstanding": 10, "emi_amount": 3}},
        )
        assert remaining.status_code == 200, remaining.text
        _assert_same_shape(
            run_script("emi_remaining", {"outstanding": 10, "emi_amount": 3}),
            remaining.json(),
        )

        unknown = client.post(
            "/agent-studio/skills/run-script",
            json={"name": "no-such-script", "payload": {}},
        )
        assert unknown.status_code == 200, unknown.text
        _assert_same_shape(run_script("no-such-script", {}), unknown.json())
