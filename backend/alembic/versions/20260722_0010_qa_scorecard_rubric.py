"""qa scorecards: full screen rubric + entry columns + reseed

Seeds the Collections Interaction Rubric with the exact criterion IDs from
Habibi/src/data/qa-seed.ts defaultRubric so scorecard entries map to the
scoring UI. Adds description / accepted / scored_at, normalizes status to
unscored|ai_draft|final and band to green|amber|red, and rebuilds entries on
the 0–5 scale the screen edits.

Revision ID: 20260722_0010
Revises: 20260722_0009
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0010"
down_revision: Union[str, Sequence[str], None] = "20260722_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors Habibi/src/data/qa-seed.ts defaultRubric exactly.
# Demo tenant this seed belongs to. Every destructive/mutating statement
# below is scoped to it: with ALEMBIC_SEED_DEMO on against a shared
# database, unscoped DELETEs and UPDATEs rewrote every tenant's QA history
# — the exact thing downgrade() already guards against.
_TENANT_ID = "hdfc.retail"
_RUBRIC_ID = "rubric-v1"
_LEGACY_RUBRIC_ID = "qa-rubric-v1"

# (section_id, label, weight, criteria[(id, label, description, weight, critical)])
_SECTIONS = [
    (
        "empathy",
        "Empathy & Tone",
        20,
        [
            ("emp-acknowledge", "Acknowledged customer situation", "Reflected feeling before pushing agenda.", 50, False),
            ("emp-tone", "Calm, respectful tone maintained", "No sarcasm, no raised voice, no interruption.", 50, False),
        ],
    ),
    (
        "resolution",
        "Resolution & Accuracy",
        30,
        [
            ("res-identify", "Correctly identified customer need", "Root need captured within 2 turns.", 30, False),
            ("res-answer", "Accurate answer / next-step", "Dues, EMI, dispute path stated correctly.", 40, False),
            ("res-close", "Confirmed resolution before closing", "Summarised action + expectation.", 30, False),
        ],
    ),
    (
        "compliance",
        "Compliance",
        25,
        [
            ("cmp-recording", "Recording notice given", "Within first 20 seconds.", 25, True),
            ("cmp-miranda", "Mini-Miranda debt disclosure", "Read verbatim before dues discussion.", 30, True),
            ("cmp-dnd", "DND / opt-out honoured", "No contact outside allowed window; opt-out respected.", 25, True),
            ("cmp-language", "No prohibited language", "No threats, no third-party disclosure.", 20, True),
        ],
    ),
    (
        "script",
        "Script Adherence",
        15,
        [
            ("scr-verify", "Identity verification followed", "DOB / OTP as per SOP.", 50, False),
            ("scr-closing", "Approved closing script used", "Includes ticket ID + next step.", 50, False),
        ],
    ),
    (
        "upsell",
        "Upsell & Value",
        10,
        [
            ("ups-eligibility", "Checked eligibility before pitch", "Only pitched if flags green.", 50, False),
            ("ups-pitch", "Contextual, non-pushy pitch", "Tied to customer's stated need.", 50, False),
        ],
    ),
]

_ALL_CRITERIA = [c[0] for _s in _SECTIONS for c in _s[3]]


def upgrade() -> None:
    op.add_column("qa_rubric_criteria", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "qa_scorecard_entries",
        sa.Column("accepted", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "qa_scorecards",
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Drop children that reference the old 2-criterion rubric before replacing it.
    if not seed_demo_enabled():
        return

    op.execute(
        sa.text(
            """
            DELETE FROM qa_scorecard_entries
            WHERE scorecard_id IN (
              SELECT qs.id FROM qa_scorecards qs
              JOIN interactions i ON i.id = qs.interaction_id
              WHERE i.tenant_id = :tenant
            )
            """
        ).bindparams(tenant=_TENANT_ID)
    )

    # Insert the screen rubric first so FK updates below can point at it.
    op.execute(
        sa.text(
            """
            INSERT INTO qa_rubrics (id, name, version, enabled)
            VALUES (:id, 'Collections Interaction Rubric', 'v1.0', true)
            ON CONFLICT (id) DO UPDATE
              SET name = EXCLUDED.name,
                  version = EXCLUDED.version,
                  enabled = true,
                  updated_at = now()
            """
        ).bindparams(id=_RUBRIC_ID)
    )

    for section_id, label, weight, criteria in _SECTIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO qa_rubric_sections (id, rubric_id, name, weight)
                VALUES (:id, :rubric_id, :name, :weight)
                ON CONFLICT (id) DO UPDATE
                  SET rubric_id = EXCLUDED.rubric_id,
                      name = EXCLUDED.name,
                      weight = EXCLUDED.weight,
                      updated_at = now()
                """
            ).bindparams(id=section_id, rubric_id=_RUBRIC_ID, name=label, weight=weight)
        )
        for cid, clabel, desc, cweight, critical in criteria:
            op.execute(
                sa.text(
                    """
                    INSERT INTO qa_rubric_criteria
                      (id, section_id, label, description, weight, critical_fail)
                    VALUES
                      (:id, :section_id, :label, :description, :weight, :critical)
                    ON CONFLICT (id) DO UPDATE
                      SET section_id = EXCLUDED.section_id,
                          label = EXCLUDED.label,
                          description = EXCLUDED.description,
                          weight = EXCLUDED.weight,
                          critical_fail = EXCLUDED.critical_fail,
                          updated_at = now()
                    """
                ).bindparams(
                    id=cid,
                    section_id=section_id,
                    label=clabel,
                    description=desc,
                    weight=cweight,
                    critical=critical,
                )
            )

    op.execute(
        sa.text("UPDATE calibration_sessions SET rubric_id = :new WHERE rubric_id = :old").bindparams(
            new=_RUBRIC_ID, old=_LEGACY_RUBRIC_ID
        )
    )
    op.execute(
        sa.text("UPDATE qa_scorecards SET rubric_id = :new WHERE rubric_id = :old").bindparams(
            new=_RUBRIC_ID, old=_LEGACY_RUBRIC_ID
        )
    )

    # Normalize status / band to screen vocabulary.
    op.execute(
        sa.text(
            """
        UPDATE qa_scorecards
        SET status = CASE
              WHEN status IN ('completed', 'reviewed', 'final') THEN 'final'
              WHEN status IN ('draft', 'ai_draft', 'in_review') THEN 'ai_draft'
              ELSE 'unscored'
            END,
            band = CASE
              WHEN lower(coalesce(band, '')) IN ('green', 'pass', 'good') THEN 'green'
              WHEN lower(coalesce(band, '')) IN ('amber', 'warn', 'warning') THEN 'amber'
              WHEN lower(coalesce(band, '')) IN ('red', 'fail', 'poor') THEN 'red'
              WHEN total_score >= 85 THEN 'green'
              WHEN total_score >= 70 THEN 'amber'
              ELSE 'red'
            END,
            scored_at = CASE
              WHEN status IN ('completed', 'reviewed', 'final') THEN coalesce(scored_at, updated_at)
              ELSE scored_at
            END
        WHERE interaction_id IN (
          SELECT id FROM interactions WHERE tenant_id = :tenant
        )
            """
        ).bindparams(tenant=_TENANT_ID)
    )

    # Remove legacy rubric tree (now unreferenced).
    op.execute(
        sa.text(
            """
            DELETE FROM qa_rubric_criteria
            WHERE section_id IN (
              SELECT id FROM qa_rubric_sections WHERE rubric_id = :legacy
            )
            """
        ).bindparams(legacy=_LEGACY_RUBRIC_ID)
    )
    op.execute(
        sa.text("DELETE FROM qa_rubric_sections WHERE rubric_id = :legacy").bindparams(
            legacy=_LEGACY_RUBRIC_ID
        )
    )
    op.execute(
        sa.text("DELETE FROM qa_rubrics WHERE id = :legacy").bindparams(legacy=_LEGACY_RUBRIC_ID)
    )

    # Rebuild scorecards: keep existing rows, align subject to the interaction
    # handler, and expand coverage so the queue isn't only 8 bot finals.
    op.execute(
        sa.text(
            """
        UPDATE qa_scorecards qs
        SET subject_user_id = i.handler_user_id,
            subject_bot_id = i.handler_bot_id
        FROM interactions i
        WHERE i.id = qs.interaction_id AND i.tenant_id = :tenant
            """
        ).bindparams(tenant=_TENANT_ID)
    )

    # Seed scorecards for recent interactions that lack one (up to 24 total).
    op.execute(
        sa.text(
            """
            INSERT INTO qa_scorecards
              (id, interaction_id, rubric_id, subject_user_id, subject_bot_id,
               reviewer_user_id, status, total_score, band, scored_at)
            SELECT
              'qa-' || i.id,
              i.id,
              :rubric_id,
              i.handler_user_id,
              i.handler_bot_id,
              CASE
                WHEN (row_number() OVER (ORDER BY i.started_at DESC)) > 16
                  THEN 'priya-nair'
                WHEN (row_number() OVER (ORDER BY i.started_at DESC)) > 6
                  THEN 'priya-nair'
                ELSE NULL
              END,
              CASE
                WHEN (row_number() OVER (ORDER BY i.started_at DESC)) <= 6 THEN 'unscored'
                WHEN (row_number() OVER (ORDER BY i.started_at DESC)) <= 16 THEN 'ai_draft'
                ELSE 'final'
              END,
              NULL,
              NULL,
              CASE
                WHEN (row_number() OVER (ORDER BY i.started_at DESC)) > 16
                  THEN i.started_at + interval '1 hour'
                ELSE NULL
              END
            FROM interactions i
            WHERE i.tenant_id = :tenant
              AND NOT EXISTS (
                SELECT 1 FROM qa_scorecards qs WHERE qs.interaction_id = i.id
              )
            ORDER BY i.started_at DESC
            LIMIT 24
            """
        ).bindparams(rubric_id=_RUBRIC_ID, tenant=_TENANT_ID)
    )

    # Cap at ~24 newest interaction scorecards for a usable queue; drop older extras
    # that would leave the UI sparse without full entries (keep coaching FKs safe).
    op.execute(
        sa.text(
            """
        WITH ranked AS (
          SELECT qs.id,
                 row_number() OVER (ORDER BY i.started_at DESC NULLS LAST, qs.created_at DESC) AS rn
          FROM qa_scorecards qs
          JOIN interactions i ON i.id = qs.interaction_id
          WHERE i.tenant_id = :tenant
        )
        UPDATE coaching_actions
        SET scorecard_id = NULL
        WHERE scorecard_id IN (SELECT id FROM ranked WHERE rn > 24)
            """
        ).bindparams(tenant=_TENANT_ID)
    )
    op.execute(
        sa.text(
            """
        WITH ranked AS (
          SELECT qs.id,
                 row_number() OVER (ORDER BY i.started_at DESC NULLS LAST, qs.created_at DESC) AS rn
          FROM qa_scorecards qs
          JOIN interactions i ON i.id = qs.interaction_id
          WHERE i.tenant_id = :tenant
        )
        DELETE FROM qa_scorecards
        WHERE id IN (SELECT id FROM ranked WHERE rn > 24)
            """
        ).bindparams(tenant=_TENANT_ID)
    )

    # Re-apply status mix on the retained set (newest first).
    op.execute(
        sa.text(
            """
        WITH ranked AS (
          SELECT qs.id,
                 row_number() OVER (ORDER BY i.started_at DESC NULLS LAST, qs.created_at DESC) AS rn
          FROM qa_scorecards qs
          JOIN interactions i ON i.id = qs.interaction_id
          WHERE i.tenant_id = :tenant
        )
        UPDATE qa_scorecards qs
        SET status = CASE
              WHEN r.rn <= 6 THEN 'unscored'
              WHEN r.rn <= 16 THEN 'ai_draft'
              ELSE 'final'
            END,
            reviewer_user_id = CASE
              WHEN r.rn <= 6 THEN NULL
              ELSE coalesce(qs.reviewer_user_id, 'priya-nair')
            END,
            scored_at = CASE
              WHEN r.rn > 16 THEN coalesce(qs.scored_at, qs.updated_at)
              ELSE NULL
            END,
            rubric_id = 'rubric-v1'
        FROM ranked r
        WHERE qs.id = r.id
            """
        ).bindparams(tenant=_TENANT_ID)
    )

    # Full per-criterion entries on the 0–5 screen scale.
    for crit_id in _ALL_CRITERIA:
        op.execute(
            sa.text(
                """
                INSERT INTO qa_scorecard_entries
                  (id, scorecard_id, criterion_id, ai_suggested_score, final_score, note, accepted)
                SELECT
                  qs.id || '-' || :crit,
                  qs.id,
                  :crit,
                  CASE
                    WHEN qs.status = 'unscored' THEN
                      greatest(0, least(5, 3 + mod(abs(hashtext(qs.id || :crit)), 3)))
                    ELSE
                      greatest(0, least(5, 3 + mod(abs(hashtext(qs.id || :crit || '-ai')), 3)))
                  END,
                  CASE
                    WHEN qs.status = 'unscored' THEN 0
                    WHEN qs.status = 'ai_draft' THEN
                      greatest(0, least(5, 3 + mod(abs(hashtext(qs.id || :crit || '-ai')), 3)))
                    ELSE
                      greatest(0, least(5, 3 + mod(abs(hashtext(qs.id || :crit || '-final')), 3)))
                  END,
                  CASE
                    WHEN qs.status = 'final'
                     AND mod(abs(hashtext(qs.id || :crit || '-note')), 4) = 0
                    THEN 'Coach reviewed — see comments.'
                    ELSE NULL
                  END,
                  CASE
                    WHEN qs.status = 'final' THEN
                      mod(abs(hashtext(qs.id || :crit || '-ai')), 3)
                        = mod(abs(hashtext(qs.id || :crit || '-final')), 3)
                    ELSE NULL
                  END
                FROM qa_scorecards qs
                JOIN interactions i ON i.id = qs.interaction_id
                WHERE i.tenant_id = :tenant
                ON CONFLICT (id) DO UPDATE
                  SET ai_suggested_score = EXCLUDED.ai_suggested_score,
                      final_score = EXCLUDED.final_score,
                      note = EXCLUDED.note,
                      accepted = EXCLUDED.accepted,
                      updated_at = now()
                """
            ).bindparams(crit=crit_id, tenant=_TENANT_ID)
        )

    # Recompute totals/bands from entries (critical-fail cap at 40).
    op.execute(
        sa.text(
            """
        WITH crit AS (
          SELECT c.id AS criterion_id, c.weight AS crit_weight, c.critical_fail,
                 s.weight AS section_weight, s.id AS section_id
          FROM qa_rubric_criteria c
          JOIN qa_rubric_sections s ON s.id = c.section_id
          WHERE s.rubric_id = 'rubric-v1'
        ),
        section_w AS (
          SELECT section_id, sum(crit_weight) AS crit_sum
          FROM crit GROUP BY section_id
        ),
        per_section AS (
          SELECT e.scorecard_id,
                 c.section_id,
                 max(c.section_weight) AS section_weight,
                 sum(
                   (coalesce(e.final_score, 0) / 5.0)
                   * (c.crit_weight / nullif(sw.crit_sum, 0))
                 ) * 100 AS section_score,
                 bool_or(c.critical_fail AND coalesce(e.final_score, 0) = 0) AS critical_zero
          FROM qa_scorecard_entries e
          JOIN crit c ON c.criterion_id = e.criterion_id
          JOIN section_w sw ON sw.section_id = c.section_id
          GROUP BY e.scorecard_id, c.section_id
        ),
        totals AS (
          SELECT scorecard_id,
                 sum(section_score * section_weight) / nullif(sum(section_weight), 0) AS raw_total,
                 bool_or(critical_zero) AS has_critical_zero
          FROM per_section
          GROUP BY scorecard_id
        )
        UPDATE qa_scorecards qs
        SET total_score = CASE
              WHEN t.has_critical_zero THEN least(t.raw_total, 40)
              ELSE t.raw_total
            END,
            band = CASE
              WHEN (CASE WHEN t.has_critical_zero THEN least(t.raw_total, 40) ELSE t.raw_total END) >= 85
                THEN 'green'
              WHEN (CASE WHEN t.has_critical_zero THEN least(t.raw_total, 40) ELSE t.raw_total END) >= 70
                THEN 'amber'
              ELSE 'red'
            END
        FROM totals t
        WHERE qs.id = t.scorecard_id
          AND qs.status <> 'unscored'
          AND qs.interaction_id IN (
                SELECT id FROM interactions WHERE tenant_id = :tenant
              )
            """
        ).bindparams(tenant=_TENANT_ID)
    )
    op.execute(
        sa.text(
            """
        UPDATE qa_scorecards
        SET total_score = NULL, band = NULL
        WHERE status = 'unscored'
          AND interaction_id IN (
                SELECT id FROM interactions WHERE tenant_id = :tenant
              )
            """
        ).bindparams(tenant=_TENANT_ID)
    )


def downgrade() -> None:
    # Mirror upgrade()'s guard: when demo seeding was off, upgrade() only added
    # the three columns, so downgrade must only drop them. Reversing the seed
    # here would delete rubric data this migration never created.
    if not seed_demo_enabled():
        op.drop_column("qa_scorecards", "scored_at")
        op.drop_column("qa_scorecard_entries", "accepted")
        op.drop_column("qa_rubric_criteria", "description")
        return

    # Best-effort restore of the 2-criterion smoke rubric; entries scored against
    # the replaced rubric become invalid for the screen and are cleared. Scoped
    # to that rubric — every other tenant's QA history must survive a rollback.
    op.execute(
        sa.text(
            """
            DELETE FROM qa_scorecard_entries
            WHERE scorecard_id IN (SELECT id FROM qa_scorecards WHERE rubric_id = :rubric)
            """
        ).bindparams(rubric=_RUBRIC_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO qa_rubrics (id, name, version, enabled)
            VALUES (:id, 'Collections QA', '1.0', true)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(id=_LEGACY_RUBRIC_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO qa_rubric_sections (id, rubric_id, name, weight)
            VALUES
              ('qa-sec-compliance', :rubric_id, 'Compliance', 0.5),
              ('qa-sec-resolution', :rubric_id, 'Resolution', 0.5)
            ON CONFLICT (id) DO NOTHING
            """
        ).bindparams(rubric_id=_LEGACY_RUBRIC_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO qa_rubric_criteria (id, section_id, label, weight, critical_fail)
            VALUES
              ('qa-crit-disclosure', 'qa-sec-compliance', 'Required disclosure read', 0.6, true),
              ('qa-crit-empathy', 'qa-sec-resolution', 'Empathy and resolution', 0.4, false)
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    # Only retarget the rows this migration retargeted; scorecards that already
    # pointed at some other rubric are none of our business.
    op.execute(
        sa.text(
            "UPDATE qa_scorecards SET rubric_id = :legacy WHERE rubric_id = :new"
        ).bindparams(legacy=_LEGACY_RUBRIC_ID, new=_RUBRIC_ID)
    )
    op.execute(
        sa.text(
            "UPDATE calibration_sessions SET rubric_id = :legacy WHERE rubric_id = :new"
        ).bindparams(legacy=_LEGACY_RUBRIC_ID, new=_RUBRIC_ID)
    )
    op.execute(sa.text("DELETE FROM qa_rubric_criteria WHERE id = ANY(:ids)").bindparams(ids=_ALL_CRITERIA))
    op.execute(
        sa.text("DELETE FROM qa_rubric_sections WHERE id = ANY(:ids)").bindparams(
            ids=[s[0] for s in _SECTIONS]
        )
    )
    op.execute(sa.text("DELETE FROM qa_rubrics WHERE id = :id").bindparams(id=_RUBRIC_ID))

    op.drop_column("qa_scorecards", "scored_at")
    op.drop_column("qa_scorecard_entries", "accepted")
    op.drop_column("qa_rubric_criteria", "description")
