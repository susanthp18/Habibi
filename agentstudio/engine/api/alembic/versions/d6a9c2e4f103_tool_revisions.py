"""Pin immutable tool revisions to published workflow definitions.

Revision ID: d6a9c2e4f103
Revises: 3a7b91c5d402
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "d6a9c2e4f103"
down_revision = "3a7b91c5d402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tool_id", sa.Integer(), sa.ForeignKey("tools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("policy", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("authored_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tool_id", "revision", name="uq_tool_revision_number"),
    )
    op.create_index("ix_tool_revisions_org_tool", "tool_revisions", ["organization_id", "tool_id"])
    op.create_table(
        "workflow_tool_bindings",
        sa.Column("workflow_definition_id", sa.Integer(), sa.ForeignKey("workflow_definitions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("node_id", sa.String(255), primary_key=True),
        sa.Column("tool_uuid", sa.String(36), primary_key=True),
        sa.Column("tool_revision_id", sa.Integer(), sa.ForeignKey("tool_revisions.id"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_workflow_tool_bindings_revision", "workflow_tool_bindings", ["tool_revision_id"])
    op.create_index("ix_workflow_tool_bindings_org", "workflow_tool_bindings", ["organization_id"])

    # Existing released agents keep their exact current tool bytes. These
    # snapshots are legacy, not customer approval for a new release.
    op.execute("""
        INSERT INTO tool_revisions
          (tool_id, organization_id, revision, snapshot, digest, state, authored_by)
        SELECT t.id, t.organization_id, 1,
          jsonb_build_object('name', t.name, 'description', t.description,
                             'category', t.category::text, 'definition', t.definition::jsonb),
          encode(sha256(convert_to(jsonb_build_object('name', t.name,
              'description', t.description, 'category', t.category::text,
              'definition', t.definition::jsonb)::text, 'UTF8')), 'hex'),
          'legacy', t.created_by
        FROM tools t
    """)
    op.execute("""
        INSERT INTO workflow_tool_bindings
          (workflow_definition_id, node_id, tool_uuid, tool_revision_id, digest, organization_id)
        SELECT DISTINCT wd.id, node->>'id', t.tool_uuid, tr.id, tr.digest, w.organization_id
        FROM workflow_definitions wd
        JOIN workflows w ON w.id = wd.workflow_id
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(wd.workflow_json::jsonb->'nodes', '[]'::jsonb)) node
        CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(node->'data'->'tool_uuids', '[]'::jsonb)) uid(value)
        JOIN tools t ON t.tool_uuid = uid.value AND t.organization_id = w.organization_id
        JOIN tool_revisions tr ON tr.tool_id = t.id AND tr.revision = 1
        WHERE wd.status IN ('published', 'archived') AND w.organization_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_table("workflow_tool_bindings")
    op.drop_table("tool_revisions")
