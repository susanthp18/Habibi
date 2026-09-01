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


def test_objectives_are_the_graphs_own_list(vocab):
    """The graph owns this vocabulary because the graph is what has to contain a
    matching entry node. An objective offered here that ``flow_graph`` does not
    know can never satisfy G-OB2."""
    import flow_graph as fg

    assert vocab["objectives"] == list(fg.OBJECTIVES)


def test_every_objective_the_editor_offers_is_one_the_card_can_hold(vocab):
    """``CardObjective.key`` is a Literal on a model with ``extra="forbid"``, so
    an unknown key fails at parse rather than at dial time — and the card that
    contains it cannot be saved at all."""
    from typing import get_args

    from agent_core.cards.schema import Objective

    assert set(vocab["objectives"]) == set(get_args(Objective))


def test_outcome_codes_are_the_closers_taxonomy(vocab):
    """G-OB6 rejects a post-call rule naming an outcome the Closer cannot write,
    and ``success`` / ``partial`` / ``stop_on`` come from the same set."""
    from agent_core.cards.compile import OUTCOME_CODES

    assert vocab["outcomeCodes"] == sorted(OUTCOME_CODES)


def test_post_call_actions_are_verbs_the_closer_implements(vocab):
    """A rule that names an action nobody implements silently does nothing,
    which is worse than no rule — hence G-OB6, and hence this list."""
    from agent_core.cards.compile import POST_CALL_ACTIONS

    assert vocab["postCallActions"] == sorted(POST_CALL_ACTIONS)


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


@pytest.mark.parametrize(
    "field,literal_name",
    [
        ("directions", "Direction"),
        ("voicemailModes", "VoicemailMode"),
        ("timeOfDay", "TimeOfDay"),
        ("poolKinds", "PoolKind"),
    ],
)
def test_the_enum_dropdowns_match_their_literals(vocab, field, literal_name):
    from typing import get_args

    from agent_core.cards import schema

    assert vocab[field] == list(get_args(getattr(schema, literal_name)))


def test_qa_modes_match_the_post_call_field(vocab):
    from typing import get_args

    from agent_core.cards.schema import CardPostCall

    assert vocab["qaModes"] == list(get_args(CardPostCall.model_fields["qa"].annotation))


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


def test_a_card_built_entirely_from_the_offered_vocabulary_validates(vocab):
    """The end the author actually cares about: pick one of everything the
    editor offers and the result parses. ``extra="forbid"`` plus five Literals
    means a single wrong string fails the whole card, not one field."""
    from agent_core.cards.schema import AgentCard

    objective = next(o for o in vocab["objectives"] if o != "inbound")
    card = AgentCard.model_validate(
        {
            "identity": {"bot_id": "vocab-probe", "slug": "vocab-probe", "display_name": "Probe"},
            "outbound": {
                "direction": vocab["directions"][-1],
                "pool_kind": vocab["poolKinds"][0],
                "objectives": [
                    {
                        "key": objective,
                        "entry_node": "step-1",
                        "success": vocab["outcomeCodes"][:2],
                        "partial": vocab["outcomeCodes"][2:4],
                        "authority_profile": vocab["authorityProfiles"][0]["name"],
                        "voicemail": {"leave": vocab["voicemailModes"][0]},
                        "cadence": "ladder",
                    }
                ],
                "cadences": [
                    {
                        "name": "ladder",
                        "per_day": vocab["dailyCap"],
                        "retry_on": vocab["retryStates"],
                        "stop_on": vocab["outcomeCodes"][:3],
                        "time_of_day": vocab["timeOfDay"][0],
                    }
                ],
                "post_call": {
                    "qa": vocab["qaModes"][0],
                    "on_outcome": [
                        {"when": vocab["outcomeCodes"][0], "do": vocab["postCallActions"][:2]}
                    ],
                },
            },
        }
    )
    assert card.outbound.dials
    assert card.outbound.cadence_for(objective).name == "ladder"
