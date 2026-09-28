"""The Outbound editor's dropdowns and the compiler's gates agree.

``card.outbound`` had no editor anywhere: nine members, three nested models and
eight compile gates reachable only by writing JSON into the database by hand.
The editor that fixes that has a failure mode the read-only tab did not, and it
is the one this file guards.

Every model in ``agent_core.cards.schema`` sets ``extra="forbid"`` and every
list field is checked by a G-OB gate. So an option the editor offers that the
backend does not know is not a cosmetic mismatch — it builds a card that fails
validation or fails a gate, and the author meets that failure at the publish
button holding a value they picked from a dropdown the app drew for them.

The defence is that the frontend restates nothing: ``/outbound/card-vocabulary``
derives every list from the definition the runtime and the compiler use. These
tests fail if a list starts being restated, or if one of those definitions moves
out from under it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="module")
def vocab(api_headers: dict[str, str]) -> dict:
    with TestClient(main.app, headers=api_headers) as client:
        response = client.get("/outbound/card-vocabulary")
        assert response.status_code == 200, response.text
        return response.json()


def test_retry_states_are_the_ones_worth_another_dial(vocab):
    """``cadence.py`` matches ``retry_on`` against the attempt's connection
    outcome *and* its state, so the offerable set is ``outbound.RETRYABLE`` —
    which is why ``voicemail_left`` belongs on it and ``refused`` does not."""
    import outbound

    assert vocab["retryStates"] == sorted(outbound.RETRYABLE)


def test_a_refusal_is_never_offered_as_retryable(vocab):
    """The borrower answered and said no. Dialling them again in four hours is
    harassment dressed as persistence, and no dropdown should make it a click.
    """
    assert "refused" not in vocab["retryStates"]
    assert "opt_out_requested" not in vocab["retryStates"]
    assert "deceased" not in vocab["retryStates"]


def test_authority_profiles_carry_the_ceiling_they_impose(vocab):
    """``profile_ceiling`` treats an unrecognised name as "no extra bound"
    rather than refusing every concession. That is right at runtime and wrong
    for an author: a typo there silently *widens* what a mission may concede,
    so the editor must offer names rather than accept them."""
    from agent_core.authority import config as authority_config

    offered = {p["name"]: p["ceilingInr"] for p in vocab["authorityProfiles"]}
    assert offered == authority_config.profile_ceilings()
    # Ordered cheapest first, so the safest choice is the one nearest the top.
    ceilings = [p["ceilingInr"] for p in vocab["authorityProfiles"]]
    assert ceilings == sorted(ceilings)


def test_the_daily_cap_is_the_one_g_ob3_enforces(vocab):
    """G-OB3 fails a cadence planning more contacts per day than the borrower's
    cap allows — every day, for every borrower on it, forever. The editor shows
    the number while it is being typed, so it has to be the same number."""
    import contact_policy

    assert vocab["dailyCap"] == contact_policy.daily_cap()


