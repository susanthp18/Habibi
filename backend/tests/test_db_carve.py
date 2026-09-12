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
import db_kb
import db_prompt_studio
import db_redaction
import db_routing
import db_sandbox
import db_treatment_holds
import db_workspace

BACKEND = Path(__file__).resolve().parents[1]

_CARVED = (
    "db_billing.py",
    "db_bot_analytics.py",
    "db_coaching.py",
    "db_dashboard.py",
    "db_evals.py",
    "db_kb.py",
    "db_kb_snapshots.py",
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
    "db_sandbox.py",
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
    "get_sandbox_run",
    "list_sandbox_scenarios",
)

_BOT_ANALYTICS_SHIMMED = (
    "bot_analytics",
)

_ROUTING_SHIMMED = (
    "_routing_action_key",
    "_routing_category",
    "_routing_eval_condition",
    "escalate_voice_interaction",
    "get_routing_rule",
    "list_routing_rule_executions",
    "list_routing_rules",
)

_REDACTION_SHIMMED = (
    "actor_is_admin",
    "get_redaction_record",
    "get_redaction_rule",
    "list_redaction_records",
    "list_redaction_rules",
)

_KB_SHIMMED = (
    "KB_GAP_MAX_CHARS",
    "get_kb_document",
    "list_kb_documents",
    "list_kb_faqs",
    "list_kb_gaps",
    "record_kb_gap",
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


def test_db_reexports_sandbox_as_the_same_objects() -> None:
    for name in _SANDBOX_SHIMMED:
        assert getattr(db, name) is getattr(db_sandbox, name), name


def test_db_reexports_bot_analytics_as_the_same_objects() -> None:
    for name in _BOT_ANALYTICS_SHIMMED:
        assert getattr(db, name) is getattr(db_bot_analytics, name), name


def test_db_reexports_routing_as_the_same_objects() -> None:
    for name in _ROUTING_SHIMMED:
        assert getattr(db, name) is getattr(db_routing, name), name


def test_db_reexports_redaction_as_the_same_objects() -> None:
    for name in _REDACTION_SHIMMED:
        assert getattr(db, name) is getattr(db_redaction, name), name


def test_db_reexports_kb_as_the_same_objects() -> None:
    for name in _KB_SHIMMED:
        assert getattr(db, name) is getattr(db_kb, name), name


def test_db_reexports_prompt_studio_as_the_same_objects() -> None:
    for name in _PROMPT_STUDIO_SHIMMED:
        assert getattr(db, name) is getattr(db_prompt_studio, name), name


def test_peeled_functions_live_in_the_carved_modules() -> None:
    assert db.billing_overview.__module__ == "db_billing"
    assert db.interaction_cost.__module__ == "db_billing"
    assert db.list_treatment_holds.__module__ == "db_treatment_holds"
    assert db.create_treatment_hold.__module__ == "db_treatment_holds"
    assert db.apply_authority.__module__ == "db_treatment_holds"
    assert db.get_dashboard.__module__ == "db_dashboard"
    assert db._inr_compact.__module__ == "db_dashboard"
    assert db.list_work_items.__module__ == "db_workspace"
    assert db._inr.__module__ == "db_workspace"
    assert db._work_item_sla.__module__ == "db_workspace"
    assert db._enacted_by_map.__module__ == "db_workspace"
    assert db.list_sandbox_scenarios.__module__ == "db_sandbox"
    assert db.get_sandbox_run.__module__ == "db_sandbox"
    assert db.bot_analytics.__module__ == "db_bot_analytics"
    assert db.list_routing_rules.__module__ == "db_routing"
    assert db.get_routing_rule.__module__ == "db_routing"
    assert db.escalate_voice_interaction.__module__ == "db_routing"
    assert db._routing_eval_condition.__module__ == "db_routing"
    assert db.list_redaction_records.__module__ == "db_redaction"
    assert db.get_redaction_record.__module__ == "db_redaction"
    assert db.actor_is_admin.__module__ == "db_redaction"
    assert db.list_kb_documents.__module__ == "db_kb"
    assert db.record_kb_gap.__module__ == "db_kb"
    assert db.get_kb_document.__module__ == "db_kb"
    assert db.get_prompt_version.__module__.startswith("db_prompt_studio.")
    assert db.get_active_deployment.__module__.startswith("db_prompt_studio.")
    assert db.publish_prompt_version.__module__.startswith("db_prompt_studio.")
    assert db.compile_agent_studio_card.__module__.startswith("db_prompt_studio.")
    assert db._map_prompt_version.__module__.startswith("db_prompt_studio.")
    assert db._prompt_voice.__module__.startswith("db_prompt_studio.")
    assert db.list_eval_reports.__module__ == "db_evals"
    assert db.save_eval_report.__module__ == "db_evals"
    assert db.create_kb_snapshot.__module__ == "db_kb_snapshots"
    assert db.create_coaching_action.__module__ == "db_coaching"
    assert db.patch_redaction_rule.__module__ == "db_redaction"
    assert db.create_routing_rule.__module__ == "db_routing"
    assert db.workspace_summary.__module__ == "db_workspace"


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


def test_carved_modules_reach_the_engine_through_db(db_tx) -> None:
    """The hazard WP-035 pinned: binding engine from db_core bypasses db_tx."""
    import db_core

    for mod in (
        db_billing,
        db_bot_analytics,
        db_dashboard,
        db_kb,
        db_prompt_studio,
        db_redaction,
        db_routing,
        db_sandbox,
        db_treatment_holds,
        db_workspace,
    ):
        assert mod._db() is db
        assert mod._db().engine is db.engine
        assert mod._db().engine is not db_core.engine


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
