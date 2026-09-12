"""The provider seed disables what it no longer ships.

``sync_seed`` only ever added: a model removed from the code seed kept its row
enabled, appeared in every picker and stayed bindable. A retired model is
disabled, not deleted -- bindings reference it and must stay visible so an
operator can move them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from agent_core.providers import persist


def test_a_model_the_seed_no_longer_ships_is_disabled_not_deleted(db_tx) -> None:
    provider = db_tx.execute(text("SELECT id FROM providers LIMIT 1")).scalar()
    if provider is None:
        persist.sync_seed()
        provider = db_tx.execute(text("SELECT id FROM providers LIMIT 1")).scalar()
    stale = f"retired-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO provider_models (id, provider_id, kind, model_id, display_name, service_class, enabled)
            VALUES (:id, :p, 'tts', :m, 'Retired model', 'x.Y', true)
            """
        ),
        {"id": stale, "p": provider, "m": stale},
    )

    stats = persist.sync_seed()

    assert stats["retired"] >= 1
    row = db_tx.execute(
        text("SELECT enabled FROM provider_models WHERE id = :id"), {"id": stale}
    ).mappings().first()
    assert row is not None, "retired, not deleted"
    assert row["enabled"] is False
    shipped_enabled = db_tx.execute(
        text("SELECT count(*) FROM provider_models WHERE enabled")
    ).scalar()
    assert shipped_enabled == len(list(persist.as_rows()))
