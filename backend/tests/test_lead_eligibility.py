"""Eligibility gating and the lead stage machine — the compliance surface.

These are pure-function tests over the flag shapes and the transition table.
Both are places where a silent regression is expensive: a weakened veto pitches
a product to someone who must not be offered it, and a missing transition rule
lets a lead be closed with no amount or no reason.
"""

from __future__ import annotations

import pytest

import capture
from capture import _promo_consent_flag, eligibility_blocks_capture
from db import _LEAD_STAGE_TRANSITIONS, _TEAM_BY_CATEGORY


def _flag(code: str, *, passed: bool, status: str, blocking: bool) -> dict:
    return {
        "code": code,
        "label": code.replace("_", " "),
        "passed": passed,
        "status": status,
        "blocking": blocking,
        "reason": f"{code} is {status}",
    }


# ------------------------------------------------------------------- vetoes


def test_an_unknown_never_blocks_however_important_it_looks():
    """The standing rule of this module. A missing bureau score is not a bad
    one, and treating it as one blocks every customer whose file is thin."""
    flags = [
        _flag("bureau_score", passed=False, status="unknown", blocking=True),
        _flag("kyc_profile", passed=False, status="unknown", blocking=True),
    ]
    assert eligibility_blocks_capture(flags) is None


def test_a_blocking_failure_blocks():
    flags = [_flag("consent_promo", passed=False, status="fail", blocking=True)]
    assert eligibility_blocks_capture(flags) is not None


def test_a_non_blocking_failure_does_not_block():
    flags = [_flag("rule_kyc", passed=False, status="fail", blocking=False)]
    assert eligibility_blocks_capture(flags) is None


def test_blocking_comes_from_the_code_not_the_label():
    """Rewording a label for the UI must not switch a compliance gate off."""
    relabelled = {
        "code": "consent_promo",
        "label": "Marketing preferences",  # no 'consent' or 'dnd' in the words
        "passed": False,
        "status": "fail",
        "blocking": True,
        "reason": "opted out",
    }
    assert eligibility_blocks_capture([relabelled]) is not None


# ------------------------------------------------------------------ consent


def test_consent_is_matched_to_the_channel_in_use():
    """An email opt-out must not silence a voice offer — it blocked every
    channel before, which nobody could explain to the business."""
    consent = {"email": "opted_out", "voice": "opted_in"}
    passed, status, _ = _promo_consent_flag(dnd=False, consent=consent, channel="voice")
    assert (passed, status) == (True, "pass")

    passed, status, _ = _promo_consent_flag(dnd=False, consent=consent, channel="email")
    assert (passed, status) == (False, "fail")


def test_dnd_blocks_every_channel():
    passed, status, _ = _promo_consent_flag(
        dnd=True, consent={"voice": "opted_in"}, channel="voice"
    )
    assert (passed, status) == (False, "fail")


def test_no_record_for_the_channel_is_unknown_not_a_pass():
    passed, status, _ = _promo_consent_flag(dnd=False, consent={}, channel="voice")
    assert status == "unknown"
    # Matches the KYC/bureau convention: unknowns carry passed=False so the UI
    # cannot render a green tick for something nobody verified.
    assert passed is False
    assert eligibility_blocks_capture(
        [{"code": "consent_promo", "passed": passed, "status": status, "blocking": True}]
    ) is None


def test_with_no_channel_context_only_a_total_opt_out_blocks():
    """An agent creating a lead by hand does not yet know the follow-up
    channel. Blocking on one closed channel would be an over-block; blocking
    when every channel is closed is just true."""
    _, status, _ = _promo_consent_flag(
        dnd=False, consent={"email": "opted_out", "voice": "opted_in"}, channel=None
    )
    assert status == "unknown"

    passed, status, _ = _promo_consent_flag(
        dnd=False, consent={"email": "opted_out", "voice": "dnd"}, channel=None
    )
    assert (passed, status) == (False, "fail")


# ------------------------------------------------------------ stage machine


@pytest.mark.parametrize("stage", ["interested", "contacted", "qualified", "won", "lost"])
def test_every_stage_has_a_transition_rule(stage):
    """A stage missing from the table is a stage nothing can leave."""
    assert stage in _LEAD_STAGE_TRANSITIONS


def test_a_stage_never_transitions_to_itself():
    for stage, allowed in _LEAD_STAGE_TRANSITIONS.items():
        assert stage not in allowed


def test_closed_stages_reopen_only_deliberately():
    """won/lost are closing states — they must not be a free-for-all, but a
    mis-clicked 'won' has to be correctable."""
    assert _LEAD_STAGE_TRANSITIONS["won"] == frozenset({"lost", "interested"})
    assert _LEAD_STAGE_TRANSITIONS["lost"] == frozenset({"won", "interested"})


def test_open_stages_can_reach_both_closing_states():
    for stage in ("interested", "contacted", "qualified"):
        assert {"won", "lost"} <= _LEAD_STAGE_TRANSITIONS[stage]


def test_every_transition_target_is_itself_a_known_stage():
    known = set(_LEAD_STAGE_TRANSITIONS)
    for stage, allowed in _LEAD_STAGE_TRANSITIONS.items():
        assert allowed <= known, f"{stage} can reach an unknown stage"


# ---------------------------------------------------------------- routing


def test_leads_route_to_a_sales_team_by_product_category():
    """Every bot-captured lead used to land on the hardcoded retail-sales queue,
    so an insurance lead sat in the loan team's list."""
    assert _TEAM_BY_CATEGORY["insurance"] == "insurance"
    assert _TEAM_BY_CATEGORY["card"] == "cards-sales"
    assert _TEAM_BY_CATEGORY["loan"] == "retail-sales"


# ------------------------------------------------------- event kind coverage


def test_new_commercial_event_kinds_are_registered():
    """emit_commercial_event raises on an unregistered kind, so a helper that
    emits one nobody added to the set fails at runtime, not at import."""
    for kind in ("offer_declined", "offer_suppressed", "close_probe_presented"):
        assert kind in capture.COMMERCIAL_KINDS
