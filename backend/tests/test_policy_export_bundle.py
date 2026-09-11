"""The regulator artefact says what the tenant runs under, not what the platform assumes.

`policy_export.bundle` hardcoded `dnd: {contactWhenDnd: False}`, emitted one
calling window, and knew nothing about the card. GRC diffs this bundle against
what was published, so a fact that never changes is a fact nobody can audit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import policy_rules
from agent_core import policy_export


def _published(monkeypatch: pytest.MonkeyPatch, rules: policy_rules.RuleSet) -> None:
    monkeypatch.setenv("POLICY_EXPORT_ENABLED", "true")
    monkeypatch.setattr(policy_rules, "resolve", lambda *a, **k: rules)
    monkeypatch.setattr(policy_export.db, "current_tenant", lambda: "t")

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(policy_export.db, "engine", SimpleNamespace(connect=lambda: _Conn()))


_RULES = policy_rules.RuleSet(
    statutory_version=7,
    rules={
        (policy_rules.KIND_CALLING_WINDOW, "voice"): {"startHour": 9, "endHour": 18},
        (policy_rules.KIND_CALLING_WINDOW, "whatsapp"): {"startHour": 8, "endHour": 21},
        (policy_rules.KIND_CHANNEL_SCRUB, None): {"lists": ["trai_ncpr", "internal_optout"]},
        (policy_rules.KIND_SUPPRESSION_STATE, None): {"kinds": ["deceased", "legal_hold"]},
    },
)

_CARD_VERSION = {
    "id": "pv-1",
    "botId": "kaia-v2-4",
    "agentCard": {"human_gates": [{"tool_name": "apply_goodwill", "require": "both"}]},
    "guardrails": {"maxTurns": 12, "maxSeconds": 300, "prohibited": ["arrest"]},
}


def test_dnd_is_the_published_rule_not_a_literal(monkeypatch) -> None:
    _published(monkeypatch, _RULES)
    monkeypatch.setattr(policy_export.db, "get_published_prompt_version", lambda bot_id=None: None)
    out = policy_export.bundle(fmt="opa")
    assert out["facts"]["dnd"] == {
        "contactWhenDnd": False,
        "scrubLists": ["trai_ncpr", "internal_optout"],
        "suppressionKinds": ["deceased", "legal_hold"],
        "ruleSetVersion": 7,
    }
    assert 'dnd_scrub_lists := ["trai_ncpr", "internal_optout"]' in out["text"]


def test_every_channel_gets_its_own_window(monkeypatch) -> None:
    _published(monkeypatch, _RULES)
    monkeypatch.setattr(policy_export.db, "get_published_prompt_version", lambda bot_id=None: None)
    facts = policy_export.bundle(fmt="opa")["facts"]
    assert facts["callingWindows"] == {
        "voice": {"startHour": 9, "endHour": 18},
        "whatsapp": {"startHour": 8, "endHour": 21},
        # Unpublished: the statutory bound, and said so rather than omitted.
        "sms": {"startHour": 8, "endHour": 19},
    }
    # The legacy single window is still the voice one.
    assert (facts["callingHours"]["startHour"], facts["callingHours"]["endHour"]) == (9, 18)
    assert 'calling_window["whatsapp"] := [8, 21]' in policy_export.bundle(fmt="opa")["text"]


def test_the_card_gates_ride_the_bundle(monkeypatch) -> None:
    _published(monkeypatch, _RULES)
    seen: list[str | None] = []

    def _get(bot_id=None):
        seen.append(bot_id)
        return _CARD_VERSION

    monkeypatch.setattr(policy_export.db, "get_published_prompt_version", _get)
    out = policy_export.bundle(fmt="opa", bot_id="kaia-v2-4")
    assert seen == ["kaia-v2-4"]
    assert out["facts"]["card"] == {
        "botId": "kaia-v2-4",
        "versionId": "pv-1",
        "humanGates": [{"tool_name": "apply_goodwill", "require": "both"}],
        "guardrails": {"maxTurns": 12, "maxSeconds": 300, "prohibited": ["arrest"]},
    }
    assert 'human_gate_require := {"apply_goodwill": "both"}' in out["text"]
    assert '"maxTurns": 12' in out["text"]
    cedar = policy_export.bundle(fmt="cedar", bot_id="kaia-v2-4")["text"]
    assert "human gates" in cedar and "apply_goodwill" in cedar


def test_no_published_version_is_absent_not_an_empty_card(monkeypatch) -> None:
    _published(monkeypatch, _RULES)
    monkeypatch.setattr(policy_export.db, "get_published_prompt_version", lambda bot_id=None: None)
    out = policy_export.bundle(fmt="opa")
    assert out["facts"]["card"] is None
    assert "human_gate_require" not in out["text"]


def test_the_wire_model_carries_every_fact() -> None:
    """The route's response_model drops what it does not declare, silently."""
    import schemas

    fields = schemas.PolicyExportBundleFactsResponse.model_fields
    assert {"dnd", "callingWindows", "card", "callingHours", "authority"} <= set(fields)
    assert {"scrubLists", "suppressionKinds", "ruleSetVersion"} <= set(
        schemas.PolicyExportDndRulesResponse.model_fields
    )
