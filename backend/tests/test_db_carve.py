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
import db_sandbox
import db_treatment_holds
import db_workspace

BACKEND = Path(__file__).resolve().parents[1]

_CARVED = (
    "db_billing.py",
    "db_bot_analytics.py",
    "db_dashboard.py",
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


def test_as_utc_lives_in_db_core() -> None:
    """Peel 4 moved ``_as_utc`` down before the workspace section left."""
    import db_core

    assert db._as_utc is db_core._as_utc
    assert db._as_utc.__module__ == "db_core"


def test_carved_modules_reach_the_engine_through_db(db_tx) -> None:
    """The hazard WP-035 pinned: binding engine from db_core bypasses db_tx."""
    import db_core

    for mod in (
        db_billing,
        db_bot_analytics,
        db_dashboard,
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
