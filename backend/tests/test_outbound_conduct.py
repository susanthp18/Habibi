"""The gaps between "the card says so" and "the code does so".

Every test here covers something that was configured, validated, versioned and
publishable — and had no effect. That is a worse failure than an unimplemented
feature, because the change log shows the operator a diff and the behaviour does
not move.

* the voicemail script disclosed the debt and omitted a required disclosure;
* ``CardPostCall.on_outcome`` was lint-only;
* ``authority_profile`` reached the mission and bounded nothing;
* ``max_duration_sec`` was a sentence in a prompt;
* ``ivr_traversal`` / ``ivr_max_sec`` were card fields nothing read;
* G-OB9 gated on an eval suite kind the schema would not accept.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from agent_core.authority import config as authority_config


# ---------------------------------------------------------------------------
# The card's post-call rules
# ---------------------------------------------------------------------------


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id FROM customers c
            WHERE c.id <> 'UNKNOWN-CALLER' ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")
    return dict(row)


def _attempt(cust: dict) -> dict:
    return {
        "id": "CA-RULES",
        "tenant_id": cust["tenant_id"],
        "customer_id": cust["id"],
        "objective": "dpd_reminder",
        "interaction_id": None,
        "phone_slot": "primary",
        "decision_id": None,
        "campaign_run_id": None,
        "bot_id": None,
    }


# ---------------------------------------------------------------------------
# Authority profiles
# ---------------------------------------------------------------------------


def test_a_profile_can_only_lower_the_matrix_cap() -> None:
    """A card cannot author itself more discretion than policy would grant."""
    assert authority_config.profile_ceiling("collections_tier1") == 250.0
    assert authority_config.profile_ceiling("none") == 0.0


def test_an_unknown_profile_adds_no_ceiling_rather_than_refusing_everything() -> None:
    """Refusing every concession on a typo would be a silent behaviour change
    dressed as a safety measure; the compile gate is where a bad name belongs."""
    assert authority_config.profile_ceiling("tier_from_a_dream") is None
    assert authority_config.profile_ceiling(None) is None
    assert authority_config.profile_ceiling("") is None


# ---------------------------------------------------------------------------
# The outbound graders
# ---------------------------------------------------------------------------


