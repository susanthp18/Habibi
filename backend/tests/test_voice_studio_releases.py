"""Releases: note required, the gate blocks, rollback restores then publishes. No engine or DB."""

import pytest

import voice_studio
import voice_studio_releases as rel

VERSIONS = [
    {"id": 30, "version_number": 3, "status": "draft"},
    {"id": 20, "version_number": 2, "status": "published"},
    {"id": 10, "version_number": 1, "status": "archived"},
]


@pytest.fixture
def engine(monkeypatch):
    calls = []

    def call(method, path, **_kw):
        calls.append((method, path))
        if path.endswith("/versions"):
            return VERSIONS
        if path.endswith("/publish"):
            return {"id": 30, "status": "published", "version_number": 4}
        return {}

    monkeypatch.setattr(voice_studio, "engine_call", call)
    monkeypatch.setattr(rel, "_gate", lambda _wf: {"ok": True, "errors": [], "channels": []})
    monkeypatch.setattr(rel, "_require_no_pending", lambda _wf: None)
    monkeypatch.setattr(rel, "_begin", lambda *_args: "attempt-1")
    monkeypatch.setattr(rel, "_finish_attempt", lambda _id, wf, _def, action, before, note, actor, version: {
        "action": action, "version": version,
        "fromVersion": before.get("version_number") if before else None, "note": note})
    return calls


def test_publish_needs_a_note(engine):
    with pytest.raises(ValueError):
        rel.publish(7, "  ", "u-1")
    assert ("POST", "/workflow/7/publish") not in engine


def test_publish_is_blocked_by_the_release_gate(engine, monkeypatch):
    monkeypatch.setattr(rel, "_gate", lambda _wf: {"ok": False, "errors": ["tool not approved"]})
    with pytest.raises(PermissionError, match="tool not approved"):
        rel.publish(7, "New greeting", "u-1")
    assert ("POST", "/workflow/7/publish") not in engine


def test_publish_records_from_and_to_versions(engine):
    assert rel.publish(7, "New greeting", "u-1") == {
        "action": "publish", "version": 4, "fromVersion": 2, "note": "New greeting"}


def test_rollback_restores_then_publishes(engine):
    out = rel.rollback(7, 10, "v2 misquotes dates", "u-1")
    assert [call for call in engine if call[0] == "POST"][-2:] == [
        ("POST", "/workflow/7/versions/10/restore"), ("POST", "/workflow/7/publish")]
    assert out["action"] == "rollback" and out["version"] == 4 and out["fromVersion"] == 2
    assert out["note"].startswith("Rolled back to version 1")


@pytest.mark.parametrize("version_id", [20, 30, 99])
def test_rollback_refuses_live_draft_or_unknown_versions(engine, version_id):
    with pytest.raises(ValueError):
        rel.rollback(7, version_id, "because", "u-1")
    assert not any(path.endswith("/restore") for _m, path in engine)


def test_revision_cap_tells_the_agent_not_to_retry(monkeypatch):
    from agent_core.tools import domain

    class Result:
        def __init__(self, error):
            self.error = error

        def to_llm(self):
            return {"ok": False, "error": self.error}

    monkeypatch.setattr(voice_studio, "_require_verified", lambda *_a: None)
    monkeypatch.setattr(domain, "create_promise_to_pay", lambda **_k: Result("promise_already_open"))
    monkeypatch.setattr(domain, "revise_promise_to_pay", lambda **_k: Result("promise_revision_cap"))
    out = voice_studio._tool_promise_to_pay({"workflow_run_id": 7}, {"amount": 100, "date": "2026-10-01"}, "i-1")
    assert out["error"] == "promise_revision_cap" and out["retry"] is False and "colleague" in out["say"]


def test_engine_refusal_reaches_the_user_as_a_conflict_with_its_reason():
    import httpx
    from fastapi import HTTPException

    from routers.voice_studio_admin import _release

    def refused():
        request = httpx.Request("POST", "http://engine/api/v1/workflow/7/publish")
        response = httpx.Response(400, json={"detail": "n1: tool t-9 has no approved revision"}, request=request)
        raise httpx.HTTPStatusError("400", request=request, response=response)

    with pytest.raises(HTTPException) as exc:
        _release(refused)
    assert exc.value.status_code == 409 and "no approved revision" in exc.value.detail
