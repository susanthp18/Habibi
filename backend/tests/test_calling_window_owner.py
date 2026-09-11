"""One owner for "is this hour inside the calling window": policy_rules.calling_window.

Nine sites decided it and two consulted the published rule set; the other
seven read the 08-19 constant, so a tenant that published 09-18 narrowed the
gate and nothing else -- the scheduler still planned 08:30 slots the gate then
refused, the detector flagged 18:30 calls the gate had admitted, and the
policy export told GRC a window the gate was not enforcing.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import policy_rules

BACKEND = Path(__file__).resolve().parents[1]
NARROW = (9, 18)


def _published(window: tuple[int, int]) -> policy_rules.RuleSet:
    return policy_rules.RuleSet(
        rules={(policy_rules.KIND_CALLING_WINDOW, "voice"): {"startHour": window[0], "endHour": window[1]}}
    )


@pytest.fixture
def narrow(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(policy_rules, "resolve", lambda *a, **k: _published(NARROW))


def test_the_owner_answers_the_published_window_else_the_bound(monkeypatch) -> None:
    monkeypatch.setattr(policy_rules, "resolve", lambda *a, **k: policy_rules.EMPTY)
    assert policy_rules.calling_window(None, "voice", tenant_id="t") == policy_rules.STATUTORY_VOICE_WINDOW
    monkeypatch.setattr(policy_rules, "resolve", lambda *a, **k: _published(NARROW))
    assert policy_rules.calling_window(None, "voice", tenant_id="t") == NARROW


def test_contact_policy_reads_its_constants_from_the_owner() -> None:
    import contact_policy

    assert (contact_policy.RBI_VOICE_START, contact_policy.RBI_VOICE_END) == policy_rules.STATUTORY_VOICE_WINDOW


def test_no_other_module_restates_the_window() -> None:
    """The names stay exported for contact_policy's callers; nothing under
    agent_core/ or the two worker modules reads them any more."""
    offenders = []
    roots = [BACKEND / "agent_core", BACKEND / "payment_events.py", BACKEND / "voice"]
    files = [p for r in roots for p in ([r] if r.is_file() else r.rglob("*.py"))]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "contact_policy":
                names = {a.name for a in node.names}
                if names & {"RBI_VOICE_START", "RBI_VOICE_END"}:
                    offenders.append(str(path.relative_to(BACKEND)))
            if isinstance(node, ast.Attribute) and node.attr in {"RBI_VOICE_START", "RBI_VOICE_END"}:
                offenders.append(str(path.relative_to(BACKEND)))
    assert not offenders, offenders


# --- the seven readers, each against a tenant that published 09-18 ----------


def test_the_scheduler_plans_inside_the_published_window(narrow) -> None:
    from agent_core.treatment import actions as A
    from agent_core.treatment import timing
    from agent_core.treatment.features import AccountFeatures

    features = AccountFeatures(customer_id="c", tenant_id="t", calling_window=NARROW)
    voice_action = next(a for a in A.SPECS if A.spec(a).channel == "voice")
    assert timing._window_for(voice_action, features) == NARROW
    assert timing._window_for(voice_action, replace(features, allowed_hours=(10, 20))) == (10, 18)


def test_the_detector_judges_against_the_published_window() -> None:
    from agent_core.compliance.detectors import DETECTORS
    from tests.test_compliance_detectors import ctx

    at_1830_ist = datetime(2026, 8, 18, 13, 0, tzinfo=timezone.utc)
    context = ctx(("agent", "hello"), direction="outbound", started_at=at_1830_ist)
    assert DETECTORS["r-dnd-win"](context) is None  # inside 08-19
    assert DETECTORS["r-dnd-win"](replace(context, calling_window=NARROW)) is not None


def test_live_qa_hours_check_reads_the_facts_window() -> None:
    from agent_core.live_qa import TurnFacts, checks

    facts = TurnFacts(channel="voice", now_hour=18, direction="outbound")
    assert checks.check_hours(facts) is None
    assert checks.check_hours(replace(facts, calling_window=NARROW)) is not None


def test_the_scorecard_hours_flag_takes_the_window() -> None:
    from agent_core.live_qa import scorecard

    row = {"channel": "voice", "started_at": datetime(2026, 8, 18, 13, 0, tzinfo=timezone.utc)}  # 18:30 IST
    assert scorecard._hours_fail(row, policy_rules.STATUTORY_VOICE_WINDOW) is False
    assert scorecard._hours_fail(row, NARROW) is True


def test_the_bounce_ladder_waits_for_the_published_window() -> None:
    import payment_events

    at_0830_ist = datetime(2026, 8, 18, 3, 0, tzinfo=timezone.utc)
    assert payment_events.next_voice_window(tz_name="Asia/Kolkata", now=at_0830_ist) == at_0830_ist
    nxt = payment_events.next_voice_window(tz_name="Asia/Kolkata", now=at_0830_ist, window=NARROW)
    assert nxt == datetime(2026, 8, 18, 3, 30, tzinfo=timezone.utc)  # 09:00 IST


def test_the_policy_export_projects_the_published_window(narrow, monkeypatch) -> None:
    from agent_core import policy_export

    monkeypatch.setenv("POLICY_EXPORT_ENABLED", "true")
    hours = policy_export.bundle(fmt="opa")["facts"]["callingHours"]
    assert (hours["startHour"], hours["endHour"]) == NARROW
