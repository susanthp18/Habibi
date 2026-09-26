"""An empty exclusions-filtered retrieval is retried on the query's own words.

VS-7956F27B36: "travel insurance for Singapore" was planned prefer_policy, the
exclusions topic filter found nothing, and the caller got the product's name
and no content.
"""

from __future__ import annotations

import kb_retrieve
from agent_core.tools import kb


def test_empty_topic_filtered_fetch_retries_unfiltered(monkeypatch) -> None:
    seen: list[object] = []

    def fake_retrieve(**kw):
        seen.append(kw.get("topic"))
        if kw.get("topic") == "exclusions":
            return {"results": []}
        return {"results": [{"docTitle": "Travel Protect360", "snippet": "Four levels of cover.", "score": 0.8}]}

    monkeypatch.setattr(kb_retrieve, "retrieve", fake_retrieve)
    st = kb.KbSearch(
        apply_intent_gate=False, bot_id=None, channel="voice", customer_text="", defaults=kb._DEFAULTS["voice"],
        gap_sink=None, intent=None, interaction_id=None, kb_snapshot_id=None, plan_budget_s=None,
        prefer_policy=True, product_hint=None, product_keys=["travel"], q="travel insurance for Singapore",
        query="travel insurance for Singapore", recent=None, record_offer=False, session_intent=None,
        should_expand_query=False, snippet_chars=None, top_k=None,
    )
    st.expanded = "travel insurance for Singapore"
    assert kb._kb_fetch(st) is None
    assert seen == ["exclusions", None]
    assert st.results and st.results[0]["snippet"] == "Four levels of cover."
