"""WP-036 peels 1–2: billing and treatment holds leave db.py via re-export.

Call sites stay ``import db``. Each carved module reaches the engine through
``_db().engine`` so the ``db_tx`` savepoint proxy still wraps writes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import db
import db_billing
import db_treatment_holds

BACKEND = Path(__file__).resolve().parents[1]

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


def test_db_reexports_billing_as_the_same_objects() -> None:
    for name in _BILLING_SHIMMED:
        assert getattr(db, name) is getattr(db_billing, name), name


def test_db_reexports_treatment_holds_as_the_same_objects() -> None:
    for name in _TREATMENT_SHIMMED:
        assert getattr(db, name) is getattr(db_treatment_holds, name), name


def test_peeled_functions_live_in_the_carved_modules() -> None:
    assert db.billing_overview.__module__ == "db_billing"
    assert db.interaction_cost.__module__ == "db_billing"
    assert db.list_treatment_holds.__module__ == "db_treatment_holds"
    assert db.create_treatment_hold.__module__ == "db_treatment_holds"
    assert db.apply_authority.__module__ == "db_treatment_holds"


def test_carved_modules_reach_the_engine_through_db(db_tx) -> None:
    """The hazard WP-035 pinned: binding engine from db_core bypasses db_tx."""
    assert db_billing._db() is db
    assert db_treatment_holds._db() is db
    assert db_billing._db().engine is db.engine
    assert db_treatment_holds._db().engine is db.engine
    assert db_billing._db().engine is not __import__("db_core").engine


def test_carved_modules_do_not_bind_engine_at_import_time() -> None:
    """A module-level engine name would capture the unwrapped Engine."""
    for filename in ("db_billing.py", "db_treatment_holds.py"):
        tree = ast.parse((BACKEND / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assert not (
                        isinstance(target, ast.Name) and target.id == "engine"
                    ), filename
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert node.target.id != "engine", filename
