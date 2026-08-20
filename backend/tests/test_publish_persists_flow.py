"""Publish is a compiler: the authored flow must persist and must be valid.

Two bugs lived here at once. ``patch_prompt_version`` never wrote the ``flow``
column, so Prompt Studio autosave of the canvas was silently dropped.
``publish_prompt_version`` never called ``validate_graph``, so an invalid graph
could become the live script. The UI disable is not enough.
"""

from __future__ import annotations

import pytest

import db
import flow_graph as fg


def _published() -> dict:
    rows = db.list_prompt_versions(limit=50)
    live = next((v for v in rows if v["status"] == "published"), None)
    assert live is not None, "seed data must include a published prompt version"
    return live


def test_patch_persists_flow_and_omitting_it_does_not_wipe(db_tx) -> None:
    draft = db.restore_prompt_version_as_draft(_published()["id"])
    graph = fg.empty_graph().model_dump()
    patched = db.patch_prompt_version(draft["id"], {"flow": graph})
    assert patched["flow"]["nodes"]
    assert patched["flow"]["nodes"][0]["key"] == "greet"

    again = db.patch_prompt_version(draft["id"], {"summary": "no flow key"})
    assert again["flow"]["nodes"][0]["key"] == "greet"
    assert again["summary"] == "no flow key"


def test_explicit_empty_flow_clears_the_authored_graph(db_tx) -> None:
    draft = db.restore_prompt_version_as_draft(_published()["id"])
    db.patch_prompt_version(draft["id"], {"flow": fg.empty_graph().model_dump()})
    cleared = db.patch_prompt_version(draft["id"], {"flow": {}})
    assert cleared["flow"] == {} or cleared["flow"].get("nodes") in (None, [])


def test_publish_rejects_an_invalid_flow(db_tx) -> None:
    draft = db.restore_prompt_version_as_draft(_published()["id"])
    graph = fg.empty_graph()
    graph.nodes[1].key = graph.nodes[0].key
    db.patch_prompt_version(draft["id"], {"flow": graph.model_dump()})
    with pytest.raises((fg.FlowInvalidError, Exception)) as exc:
        db.publish_prompt_version(draft["id"], "should not ship")
    err = exc.value
    if isinstance(err, fg.FlowInvalidError):
        assert err.http_detail()["code"] == "flow_invalid"
    else:
        from agent_core.cards.compile import CompileError

        assert isinstance(err, CompileError)
        g1 = next(g for g in err.report.gates if g.gate == "G1")
        assert g1.status == "fail"

    # Status must not have flipped — the previous published version is still live.
    still = next(v for v in db.list_prompt_versions(limit=50) if v["id"] == draft["id"])
    assert still["status"] == "draft"
