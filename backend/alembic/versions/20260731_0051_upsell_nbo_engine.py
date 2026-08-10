"""Upsell / cross-sell: closed_at, product catalog depth, and the NBO engine.

Revision ID: 20260731_0051
Revises: 20260727_0050

Three things land together because they are one feature:

1. ``leads.closed_at`` — the UI derived "won this week" and "average time to
   close" from a field the API never populated, so both tiles read zero
   forever. The column has to exist before ``patch_lead`` can stamp it.

2. Product catalog depth (``category``/``family``/``roi_numeric``/
   ``margin_score``/``is_active``/``channels`` + populated ticket bands). The
   recommender cannot rank what it cannot compare, and it cannot bound a
   suggested amount without a ticket band. Today the model picks a product id
   out of a comma-separated list in a tool description.

3. ``product_relations`` / ``product_campaigns`` / ``offer_decisions`` — the
   complementarity graph, the marketing switchboard, and the append-only
   decision log. The log is deliberately written from day one in shadow mode:
   without it there is no offline evaluation and no labelled data to train a
   propensity model on later.

Uses op.create_table / op.add_column (not op.execute) so the CI drift assertion
in .github/workflows/backend-pytest.yml can see them and fail if sql/*.sql is
not kept in step.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0051"
down_revision: Union[str, Sequence[str], None] = "20260727_0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- leads
    op.add_column("leads", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_leads_closed_at", "leads", ["closed_at"])
    op.create_index(
        "idx_leads_customer_product_stage", "leads", ["customer_id", "product_id", "stage"]
    )
    # Best-effort backfill from the audit trail so historical won/lost leads
    # stop reporting a null close date. activity_events is the only place the
    # transition was ever recorded.
    op.execute(
        """
        UPDATE leads l
        SET closed_at = e.at
        FROM (
            SELECT entity_id, MAX(at) AS at
            FROM activity_events
            WHERE entity_type = 'lead' AND kind IN ('lead_updated', 'lead_created')
            GROUP BY entity_id
        ) e
        WHERE e.entity_id = l.id
          AND l.stage IN ('won', 'lost')
          AND l.closed_at IS NULL
        """
    )
    # Anything still null (seeded rows with no audit trail) falls back to
    # captured_at — wrong by hours, but a closed lead with no close date breaks
    # every downstream aggregate.
    op.execute(
        "UPDATE leads SET closed_at = captured_at "
        "WHERE stage IN ('won','lost') AND closed_at IS NULL AND captured_at IS NOT NULL"
    )

    # ------------------------------------------------------------- products
    op.add_column("products", sa.Column("category", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("family", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("roi_numeric", sa.Numeric(6, 3), nullable=True))
    op.add_column("products", sa.Column("tenor_months_min", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("tenor_months_max", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column(
            "margin_score", sa.Numeric(5, 3), nullable=False, server_default=sa.text("0.500")
        ),
    )
    op.add_column(
        "products",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "products",
        sa.Column(
            "channels",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['voice','whatsapp','agent']::TEXT[]"),
        ),
    )
    op.create_index("idx_products_is_active", "products", ["is_active"])

    # --------------------------------------------------------- NBO catalog
    op.create_table(
        "product_relations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Text(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "related_product_id",
            sa.Text(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column(
            "affinity", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "relation IN ('complements','requires','excludes','upgrades')",
            name="ck_product_relations_relation",
        ),
    )
    op.create_index(
        "ux_product_relations_triple",
        "product_relations",
        ["product_id", "related_product_id", "relation"],
        unique=True,
    )
    op.create_index(
        "idx_product_relations_related", "product_relations", ["related_product_id"]
    )

    op.create_table(
        "product_campaigns",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Text(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # NULL means "no restriction". An empty array would mean "matches
        # nothing" — a much easier mistake to make by accident.
        sa.Column("segment_in", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("risk_not_in", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "priority", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.500")
        ),
        sa.Column("quota_total", sa.Integer(), nullable=True),
        sa.Column("quota_used", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_product_campaigns_product", "product_campaigns", ["product_id"])
    op.create_index("idx_product_campaigns_enabled", "product_campaigns", ["enabled"])

    op.create_table(
        "offer_decisions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Text(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.Text(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "interaction_id",
            sa.Text(),
            sa.ForeignKey("interactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False, server_default=sa.text("'live'")),
        sa.Column("recommender", sa.Text(), nullable=False),
        sa.Column("recommender_version", sa.Text(), nullable=False),
        sa.Column("feature_schema_version", sa.Text(), nullable=False),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "chosen_product_id",
            sa.Text(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("score", sa.Numeric(6, 4), nullable=True),
        sa.Column(
            "presented", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "lead_id", sa.Text(), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("mode IN ('live','shadow')", name="ck_offer_decisions_mode"),
        sa.CheckConstraint(
            "response IS NULL OR response IN ('interested','declined','deferred','not_reached')",
            name="ck_offer_decisions_response",
        ),
    )
    op.create_index("idx_offer_decisions_customer", "offer_decisions", ["customer_id"])
    op.create_index("idx_offer_decisions_interaction", "offer_decisions", ["interaction_id"])
    op.create_index("idx_offer_decisions_lead", "offer_decisions", ["lead_id"])
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_offer_decisions_cooldown "
        "ON offer_decisions(customer_id, chosen_product_id, created_at DESC)"
    )

    # updated_at triggers for the new mutable tables (and leads, which was
    # never in the trigger list despite carrying the column).
    op.execute(
        """
        DO $$
        DECLARE t TEXT;
        BEGIN
          FOREACH t IN ARRAY ARRAY['product_campaigns', 'leads'] LOOP
            EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I', t, t);
            EXECUTE format(
              'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I '
              'FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t
            );
          END LOOP;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_product_campaigns_updated_at ON product_campaigns")
    op.execute("DROP TRIGGER IF EXISTS trg_leads_updated_at ON leads")

    op.drop_index("idx_offer_decisions_cooldown", table_name="offer_decisions")
    op.drop_index("idx_offer_decisions_lead", table_name="offer_decisions")
    op.drop_index("idx_offer_decisions_interaction", table_name="offer_decisions")
    op.drop_index("idx_offer_decisions_customer", table_name="offer_decisions")
    op.drop_table("offer_decisions")

    op.drop_index("idx_product_campaigns_enabled", table_name="product_campaigns")
    op.drop_index("idx_product_campaigns_product", table_name="product_campaigns")
    op.drop_table("product_campaigns")

    op.drop_index("idx_product_relations_related", table_name="product_relations")
    op.drop_index("ux_product_relations_triple", table_name="product_relations")
    op.drop_table("product_relations")

    op.drop_index("idx_products_is_active", table_name="products")
    for column in (
        "channels",
        "is_active",
        "margin_score",
        "tenor_months_max",
        "tenor_months_min",
        "roi_numeric",
        "description",
        "family",
        "category",
    ):
        op.drop_column("products", column)

    op.drop_index("idx_leads_customer_product_stage", table_name="leads")
    op.drop_index("idx_leads_closed_at", table_name="leads")
    op.drop_column("leads", "closed_at")
