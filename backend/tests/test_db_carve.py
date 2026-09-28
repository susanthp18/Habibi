"""WP-036 peels: carved sections leave db.py via re-export.

Call sites stay ``import db``. Each carved module reaches the engine through
``_db().engine`` so the ``db_tx`` savepoint proxy still wraps writes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import db
import db_billing
import db_bot_analytics
import db_dashboard
import db_redaction
import db_routing
import db_treatment_holds
import db_workspace

BACKEND = Path(__file__).resolve().parents[1]

_CARVED = (
    "db_billing.py",
    "db_bot_analytics.py",
    "db_coaching.py",
    "db_dashboard.py",
    "db_evals.py",
    "db_prompt_studio/__init__.py",
    "db_prompt_studio/cards.py",
    "db_prompt_studio/common.py",
    "db_prompt_studio/compile.py",
    "db_prompt_studio/deployments.py",
    "db_prompt_studio/publish.py",
    "db_prompt_studio/versions.py",
    "db_prompt_studio/voices.py",
    "db_redaction.py",
    "db_routing.py",
    "db_treatment_holds.py",
    "db_workspace.py",
)

_BILLING_SHIMMED = (
    "_BILLING_ENVS",
    "_billing_as_of",
    "billing_export_csv",
    "billing_overview",
    "delete_budget_rule",
    "interaction_cost",
    "upsert_budget_rule",
)

_TREATMENT_SHIMMED = (
    "HOLD_KINDS",
    "HOLD_SOURCES",
    "apply_authority",
    "create_treatment_hold",
    "list_treatment_cases",
    "list_treatment_holds",
    "next_authority",
    "next_treatment",
    "release_treatment_hold",
    "treatment_insights",
    "treatment_metrics",
    "treatment_model_health",
    "treatment_models",
)

_DASHBOARD_SHIMMED = (
    "_inr_compact",
    "get_dashboard",
)

_WORKSPACE_SHIMMED = (
    "_enacted_by_map",
    "_inr",
    "_work_item_sla",
    "list_work_items",
)

_SANDBOX_SHIMMED = (
)

_BOT_ANALYTICS_SHIMMED = (
    "bot_analytics",
)

_ROUTING_SHIMMED = (
    "escalate_voice_interaction",
)


_REDACTION_SHIMMED = (
    "actor_is_admin",
    "get_redaction_record",
    "get_redaction_rule",
    "list_redaction_records",
    "list_redaction_rules",
)

_PROMPT_STUDIO_SHIMMED = (
    "DEFAULT_BOT_ID",
    "_DEFAULT_PERSONA",
    "_DEFAULT_VOICE",
    "_DEFAULT_GUARDRAILS",
    "_handoff_edges",
    "_map_prompt_version",
    "_prompt_voice",
    "compile_agent_studio_card",
    "get_active_deployment",
    "get_agent_studio_card",
    "get_prompt_version",
    "list_agent_studio_cards",
    "list_prompt_versions",
    "publish_prompt_version",
)


def test_db_reexports_billing_as_the_same_objects() -> None:
    for name in _BILLING_SHIMMED:
        assert getattr(db, name) is getattr(db_billing, name), name


def test_db_reexports_treatment_holds_as_the_same_objects() -> None:
    for name in _TREATMENT_SHIMMED:
        assert getattr(db, name) is getattr(db_treatment_holds, name), name


def test_db_reexports_dashboard_as_the_same_objects() -> None:
    for name in _DASHBOARD_SHIMMED:
        assert getattr(db, name) is getattr(db_dashboard, name), name


def test_db_reexports_workspace_as_the_same_objects() -> None:
    for name in _WORKSPACE_SHIMMED:
        assert getattr(db, name) is getattr(db_workspace, name), name


def test_db_reexports_bot_analytics_as_the_same_objects() -> None:
    for name in _BOT_ANALYTICS_SHIMMED:
        assert getattr(db, name) is getattr(db_bot_analytics, name), name


def test_db_reexports_routing_as_the_same_objects() -> None:
    for name in _ROUTING_SHIMMED:
        assert getattr(db, name) is getattr(db_routing, name), name


def test_db_reexports_redaction_as_the_same_objects() -> None:
    for name in _REDACTION_SHIMMED:
        assert getattr(db, name) is getattr(db_redaction, name), name


def test_as_utc_lives_in_db_core() -> None:
    """Peel 4 moved ``_as_utc`` down before the workspace section left."""
    import db_core

    assert db._as_utc is db_core._as_utc
    assert db._as_utc.__module__ == "db_core"


def test_speaker_screen_lives_in_db_core() -> None:
    """Peel 8 moved ``_speaker_screen`` down before the redaction section left."""
    import db_core

    assert db._speaker_screen is db_core._speaker_screen
    assert db._speaker_screen.__module__ == "db_core"


def test_carved_modules_do_not_bind_engine_at_import_time() -> None:
    """A module-level engine name would capture the unwrapped Engine."""
    for filename in _CARVED:
        tree = ast.parse((BACKEND / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assert not (
                        isinstance(target, ast.Name) and target.id == "engine"
                    ), filename
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert node.target.id != "engine", filename
