"""Skill import and export at the HTTP layer.

Import used to hand a bad zip or a non-UTF-8 body straight to the caller as a
500 with a traceback, and bypassed ``_handle_write`` so a pack parse error was
a 500 too. Export streamed a 200 zip whose ``SKILL.md`` was empty -- an export
that imports as nothing.
"""

from __future__ import annotations

import io
import zipfile

import pytest


@pytest.fixture()
def client(monkeypatch, db_tx):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "skill-io-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "skill-io-key", "X-Actor-User-Id": "priya-nair"}


def _post(client, name: str, body: bytes):
    return client.post(
        "/agent-studio/skills/import",
        files={"file": (name, body, "application/octet-stream")},
        headers=HEADERS,
    )


def test_a_bad_zip_is_the_clients_error(client) -> None:
    r = _post(client, "pack.zip", b"this is not a zip archive")
    assert r.status_code == 400
    assert r.json()["detail"] == "skill_archive_unreadable"


def test_a_non_utf8_body_is_the_clients_error(client) -> None:
    r = _post(client, "SKILL.md", b"\xff\xfe not text")
    assert r.status_code == 400
    assert r.json()["detail"] == "skill_body_not_utf8"


def test_a_pack_that_does_not_parse_is_not_a_500(client) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\ndescription: no name\n---\nbody\n")
    r = _post(client, "pack.zip", buf.getvalue())
    assert r.status_code in (409, 422), r.text
    assert "skill_missing_name" in r.json()["detail"]


def test_export_refuses_an_empty_body(client, monkeypatch) -> None:
    from agent_core.skills import persist

    monkeypatch.setattr(
        persist, "get_skill", lambda skill_id: {"id": skill_id, "slug": "empty", "markdown": "", "pack": {}}
    )
    r = client.get("/agent-studio/skills/sk-empty/export", headers=HEADERS)
    assert r.status_code == 409
    assert r.json()["detail"] == "skill_body_empty"
