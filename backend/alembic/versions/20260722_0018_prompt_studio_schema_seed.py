"""prompt studio: label/summary columns + rich seed

Aligns prompt_versions / persona_presets / tts_voices / bot_deployments with
Habibi prompt-studio-seed.ts. Maintains live-config invariant:
  active prod deployment.prompt_version_id == single published prompt version.

DOWNGRADE IS ONE-WAY for the seeded data. upgrade() deletes the legacy prompt
versions, voices, persona presets and deployments and retargets the foreign
keys that pointed at them, without snapshotting the originals. downgrade()
therefore removes the rows this revision inserted and reverses the schema
changes, but the pre-existing legacy rows and their FK targets are NOT
restored — recovering those needs a database restore taken before the upgrade.

Revision ID: 20260722_0018
Revises: 20260722_0017
Create Date: 2026-07-22
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0018"
down_revision: Union[str, Sequence[str], None] = "20260722_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_ID = "hdfc.retail"

EMPATHETIC_PROMPT = """You are {agent_name}, an inbound collections voice agent for {bank_name}.
Greet {customer_name} warmly and acknowledge their situation before discussing dues.
Reference their account {account_no} and the overdue amount of {overdue_amount} due on {due_date}.
Speak in {language}. Be patient, empathetic and non-judgemental.
Always disclose that the call is recorded for quality and compliance.
Never threaten legal action. Offer Promise-to-Pay options when the customer signals hardship."""

FIRM_PROMPT = """You are {agent_name}, a collections agent for {bank_name}.
Address {customer_name} directly and state the purpose of the call within the first two sentences.
Clearly state the overdue amount {overdue_amount} on account {account_no}, past due since {due_date}.
Speak in {language}. Be professional, direct and outcome-oriented.
Disclose call recording. Do not promise waivers. Escalate to a human on any dispute."""

COMPLIANCE_PROMPT = """You are {agent_name}, a compliance-first collections agent for {bank_name}.
Begin every call with the recording disclosure and verify caller identity before sharing any account information.
Reference {customer_name}, account {account_no}, dues {overdue_amount}, due on {due_date} only after verification.
Speak in {language}. Never quote interest rates. Never promise fee waivers. Escalate on any dispute or hardship signal."""

UPSELL_PROMPT = """You are {agent_name}, a collections + relationship voice agent for {bank_name}.
Resolve {customer_name}'s query about their overdue {overdue_amount} on account {account_no} first.
Once the primary query is addressed, and eligibility permits, gently introduce one relevant product offer.
Speak in {language}. Do not push if the customer is stressed or has raised a dispute."""

DEFAULT_GUARDRAILS: dict[str, Any] = {
    "prohibited": ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment"],
    "escalateAbuse": True,
    "escalateLegal": True,
    "neverQuoteRate": True,
    "neverPromiseWaiver": True,
    "alwaysDiscloseRecording": True,
    "refusePoliticsReligion": True,
    "maxTurns": 20,
    "maxSeconds": 480,
}

DEFAULT_VOICE: dict[str, Any] = {
    "voiceId": "priya",
    "speed": 1.0,
    "pitch": 0,
    "warmth": 62,
    "pauseMs": 320,
    "sampleText": "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
}

SAMPLE_TEXT = DEFAULT_VOICE["sampleText"]

_TTS: list[dict[str, Any]] = [
    {"id": "priya", "name": "Priya", "gender": "Female", "accent": "Indian English", "azure": "en-IN-NeerjaNeural"},
    {"id": "anjali", "name": "Anjali", "gender": "Female", "accent": "Hindi-English", "azure": "en-IN-AashiNeural"},
    {"id": "neha", "name": "Neha", "gender": "Female", "accent": "Neutral English", "azure": "en-IN-NeerjaNeural"},
    {"id": "ravi", "name": "Ravi", "gender": "Male", "accent": "Indian English", "azure": "en-IN-PrabhatNeural"},
    {"id": "arjun", "name": "Arjun", "gender": "Male", "accent": "Hindi-English", "azure": "en-IN-KunalNeural"},
    {"id": "kabir", "name": "Kabir", "gender": "Male", "accent": "Neutral English", "azure": "en-IN-PrabhatNeural"},
]

_PRESETS: list[dict[str, Any]] = [
    {
        "id": "empathetic",
        "name": "Empathetic Collector",
        "config": {
            "label": "Empathetic Collector",
            "description": "Warm, patient, hardship-aware",
            "traits": {"empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60, "upsell": 20},
            "promptTemplate": EMPATHETIC_PROMPT,
        },
    },
    {
        "id": "firm",
        "name": "Firm Collector",
        "config": {
            "label": "Firm Collector",
            "description": "Direct, outcome-focused",
            "traits": {"empathy": 35, "firmness": 80, "formality": 65, "verbosity": 40, "upsell": 15},
            "promptTemplate": FIRM_PROMPT,
        },
    },
    {
        "id": "compliance",
        "name": "Compliance-First",
        "config": {
            "label": "Compliance-First",
            "description": "Every disclosure, every time",
            "traits": {"empathy": 55, "firmness": 55, "formality": 90, "verbosity": 55, "upsell": 5},
            "promptTemplate": COMPLIANCE_PROMPT,
        },
    },
    {
        "id": "upsell",
        "name": "Upsell-Focused",
        "config": {
            "label": "Upsell-Focused",
            "description": "Resolve, then convert",
            "traits": {"empathy": 65, "firmness": 45, "formality": 55, "verbosity": 55, "upsell": 75},
            "promptTemplate": UPSELL_PROMPT,
        },
    },
]


def _persona(traits: dict[str, int], *, language: str = "English", fallback: list[str] | None = None) -> dict[str, Any]:
    return {
        "traits": traits,
        "language": language,
        "fallbackLanguages": fallback if fallback is not None else ["Hindi"],
    }


def _versions() -> list[dict[str, Any]]:
    emp = _PRESETS[0]["config"]["traits"]
    firm = _PRESETS[1]["config"]["traits"]
    comp = _PRESETS[2]["config"]["traits"]
    return [
        {
            "id": "v1_4",
            "author_user_id": "anita-rao",
            "status": "published",
            "label": "v1.4",
            "summary": "+ recording disclosure, empathy 70→75",
            "prompt": EMPATHETIC_PROMPT,
            "persona": _persona({**emp, "empathy": 75}),
            "voice": {**DEFAULT_VOICE},
            "guardrails": {**DEFAULT_GUARDRAILS},
            "created_at": "2026-07-20T10:00:00+00:00",
        },
        {
            "id": "v1_3",
            "author_user_id": "anita-rao",
            "status": "archived",
            "label": "v1.3",
            "summary": "+ upsell-focused fallback path",
            "prompt": EMPATHETIC_PROMPT.replace("Offer Promise-to-Pay", "Offer Promise-to-Pay or product upgrade"),
            "persona": _persona({**emp, "upsell": 40}),
            "voice": {**DEFAULT_VOICE, "warmth": 55},
            "guardrails": {**DEFAULT_GUARDRAILS, "neverPromiseWaiver": False},
            "created_at": "2026-07-16T10:00:00+00:00",
        },
        {
            "id": "v1_2",
            "author_user_id": "vikram-shah",
            "status": "archived",
            "label": "v1.2",
            "summary": "− legal-threat language, + Hindi fallback",
            "prompt": FIRM_PROMPT,
            "persona": _persona(firm, fallback=["Hindi", "Marathi"]),
            "voice": {**DEFAULT_VOICE, "voiceId": "ravi"},
            "guardrails": {**DEFAULT_GUARDRAILS, "prohibited": ["police", "arrest", "harassment"]},
            "created_at": "2026-07-10T10:00:00+00:00",
        },
        {
            "id": "v1_1",
            "author_user_id": "vikram-shah",
            "status": "archived",
            "label": "v1.1",
            "summary": "initial compliance pass",
            "prompt": COMPLIANCE_PROMPT.replace("Never quote interest rates.", ""),
            "persona": _persona(comp),
            "voice": {**DEFAULT_VOICE, "warmth": 45},
            "guardrails": {**DEFAULT_GUARDRAILS, "neverQuoteRate": False},
            "created_at": "2026-07-02T10:00:00+00:00",
        },
        {
            "id": "v1_0",
            "author_user_id": "anita-rao",
            "status": "archived",
            "label": "v1.0",
            "summary": "first draft",
            "prompt": "You are a collections agent. Collect the overdue amount.",
            "persona": _persona(emp),
            "voice": {**DEFAULT_VOICE},
            "guardrails": {
                **DEFAULT_GUARDRAILS,
                "prohibited": [],
                "alwaysDiscloseRecording": False,
                "escalateAbuse": False,
            },
            "created_at": "2026-06-22T10:00:00+00:00",
        },
    ]


def upgrade() -> None:
    op.execute("ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS label TEXT")
    op.execute(
        "ALTER TABLE prompt_versions ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT ''"
    )

    if not seed_demo_enabled():
        return

    conn = op.get_bind()

    # Authors used by version history. `team_id` FKs to teams — a partially
    # seeded database may not have the hard-coded 'supervisors' team, which
    # made this insert fail the whole revision. Resolve an existing team for
    # the tenant, falling back to NULL rather than inventing one.
    team_id = conn.execute(
        sa.text(
            """
            SELECT id FROM teams
            WHERE tenant_id = :tenant_id
            ORDER BY (id = 'supervisors') DESC, id
            LIMIT 1
            """
        ),
        {"tenant_id": TENANT_ID},
    ).scalar()

    for user_id, name in (("anita-rao", "Anita Rao"), ("vikram-shah", "Vikram Shah")):
        conn.execute(
            sa.text(
                """
                INSERT INTO users (id, tenant_id, team_id, name, email, status)
                VALUES (:id, :tenant_id, :team_id, :name, :email, 'active')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """
            ),
            {
                "id": user_id,
                "tenant_id": TENANT_ID,
                "team_id": team_id,
                "name": name,
                "email": f"{user_id}@hdfc.example",
            },
        )

    # Insert new Azure Speech voices before retargeting FKs
    for v in _TTS:
        cfg = {
            "gender": v["gender"],
            "accent": v["accent"],
            "duration": "0:03",
            "azureVoiceName": v["azure"],
        }
        conn.execute(
            sa.text(
                """
                INSERT INTO tts_voices (id, provider, name, config, enabled)
                VALUES (:id, 'azure-speech', :name, CAST(:config AS jsonb), true)
                ON CONFLICT (id) DO UPDATE SET
                  provider = EXCLUDED.provider,
                  name = EXCLUDED.name,
                  config = EXCLUDED.config,
                  enabled = EXCLUDED.enabled,
                  updated_at = now()
                """
            ),
            {"id": v["id"], "name": v["name"], "config": json.dumps(cfg)},
        )

    for p in _PRESETS:
        conn.execute(
            sa.text(
                """
                INSERT INTO persona_presets (id, name, config)
                VALUES (:id, :name, CAST(:config AS jsonb))
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  config = EXCLUDED.config,
                  updated_at = now()
                """
            ),
            {"id": p["id"], "name": p["name"], "config": json.dumps(p["config"])},
        )

    # Insert new prompt versions (v1_4 published). Clear any other published first
    # only after v1_4 exists — order: insert all as archived, then flip v1_4.
    for ver in _versions():
        status = "archived" if ver["id"] != "v1_4" else "draft"
        conn.execute(
            sa.text(
                """
                INSERT INTO prompt_versions (
                  id, author_user_id, status, prompt, persona, voice, guardrails,
                  label, summary, created_at, updated_at
                )
                VALUES (
                  :id, :author_user_id, :status, :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  :label, :summary, CAST(:created_at AS timestamptz), CAST(:created_at AS timestamptz)
                )
                ON CONFLICT (id) DO UPDATE SET
                  author_user_id = EXCLUDED.author_user_id,
                  -- Existing rows must also land on the computed archived/draft
                  -- state; the v1_4 publish step below still overrides it.
                  status = EXCLUDED.status,
                  prompt = EXCLUDED.prompt,
                  persona = EXCLUDED.persona,
                  voice = EXCLUDED.voice,
                  guardrails = EXCLUDED.guardrails,
                  label = EXCLUDED.label,
                  summary = EXCLUDED.summary,
                  updated_at = now()
                """
            ),
            {
                "id": ver["id"],
                "author_user_id": ver["author_user_id"],
                "status": status,
                "prompt": ver["prompt"],
                "persona": json.dumps(ver["persona"]),
                "voice": json.dumps(ver["voice"]),
                "guardrails": json.dumps(ver["guardrails"]),
                "label": ver["label"],
                "summary": ver["summary"],
                "created_at": ver["created_at"],
            },
        )

    # Retarget FKs away from legacy stub ids
    conn.execute(sa.text("UPDATE bot_deployments SET prompt_version_id = 'v1_4' WHERE prompt_version_id = 'prompt-v2-4'"))
    conn.execute(sa.text("UPDATE sandbox_runs SET prompt_version_id = 'v1_4' WHERE prompt_version_id = 'prompt-v2-4'"))
    conn.execute(
        sa.text(
            "UPDATE analytics_kb_gap_links SET prompt_version_id = 'v1_4' WHERE prompt_version_id = 'prompt-v2-4'"
        )
    )
    conn.execute(sa.text("UPDATE bot_deployments SET tts_voice_id = 'priya' WHERE tts_voice_id = 'voice-hindi-en-1'"))

    # Promote v1_4 as sole published (archive everything else including legacy)
    conn.execute(sa.text("UPDATE prompt_versions SET status = 'archived' WHERE status = 'published'"))
    conn.execute(
        sa.text(
            """
            UPDATE prompt_versions
            SET status = 'published', label = 'v1.4',
                summary = '+ recording disclosure, empathy 70→75',
                updated_at = now()
            WHERE id = 'v1_4'
            """
        )
    )

    # Ensure active prod deployment matches invariant
    conn.execute(
        sa.text(
            """
            UPDATE bot_deployments
            SET prompt_version_id = 'v1_4',
                tts_voice_id = 'priya',
                environment = 'production',
                status = 'active',
                voice_config = CAST(:voice AS jsonb),
                updated_at = now()
            WHERE id = 'DEP-2026-07-PROD'
            """
        ),
        {"voice": json.dumps(DEFAULT_VOICE)},
    )
    # If DEP row missing (unlikely), insert it
    conn.execute(
        sa.text(
            """
            INSERT INTO bot_deployments (
              id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
              environment, status, published_by_user_id, published_at,
              rollback_deployment_id, voice_config
            )
            SELECT
              'DEP-2026-07-PROD', 'kaia-v2-4', 'v1_4',
              (SELECT id FROM kb_snapshots WHERE id = 'kb-snapshot-2026-07'),
              'priya', 'production', 'active', 'priya-nair',
              CAST('2026-07-21T08:30:00+00:00' AS timestamptz), NULL,
              CAST(:voice AS jsonb)
            WHERE NOT EXISTS (SELECT 1 FROM bot_deployments WHERE id = 'DEP-2026-07-PROD')
            """
        ),
        {"voice": json.dumps(DEFAULT_VOICE)},
    )

    # Drop legacy stub rows (FKs already retargeted)
    conn.execute(sa.text("DELETE FROM prompt_versions WHERE id = 'prompt-v2-4'"))
    conn.execute(sa.text("DELETE FROM tts_voices WHERE id = 'voice-hindi-en-1'"))
    conn.execute(sa.text("DELETE FROM persona_presets WHERE id = 'persona-compliant-collector'"))


def downgrade() -> None:
    op.execute("ALTER TABLE prompt_versions DROP COLUMN IF EXISTS summary")
    op.execute("ALTER TABLE prompt_versions DROP COLUMN IF EXISTS label")
