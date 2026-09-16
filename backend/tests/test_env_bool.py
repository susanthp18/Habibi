"""One truth set for every environment flag, including ``on``.

``env_utils`` shipped ``env_int`` and ``env_float`` and no ``env_bool``, so the
twenty-six boolean sites each rolled their own. Four dialects. The sharp edge
was ``MINIO_SECURE=on`` disabling TLS, because ``storage.py`` omitted ``"on"``
while twenty other sites accepted it. This file pins the shared helper, pins
that ``on`` turns MinIO TLS on, pins that a typo does not force plaintext,
and pins that application getenv-booleans go through ``env_bool`` rather than
a private set.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

import env_utils
from agent_core import platform_flags as flags

BACKEND = Path(__file__).resolve().parents[1]

# Pruned from the walk, not filtered after. ``.venv`` must never be descended
# into — a scan of site-packages hangs the suite.
_SKIP_DIRS = {".venv", "venv", "__pycache__", ".ruff_cache", "htmlcov", "tests", "alembic"}


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_BOOL_TEST", raising=False)


def test_env_bool_is_public_on_the_leaf_module() -> None:
    assert callable(env_utils.env_bool)
    assert "env_bool" in env_utils.__all__
    assert "env_str" in env_utils.__all__


def test_env_str_strips_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_STR_TEST", raising=False)
    assert env_utils.env_str("ENV_STR_TEST", "fallback") == "fallback"
    monkeypatch.setenv("ENV_STR_TEST", "  value  ")
    assert env_utils.env_str("ENV_STR_TEST") == "value"
    monkeypatch.setenv("ENV_STR_TEST", "   ")
    assert env_utils.env_str("ENV_STR_TEST", "fallback") == "fallback"


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE", "On", " yes "])
def test_the_truth_set_includes_on(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("ENV_BOOL_TEST", raw)
    assert env_utils.env_bool("ENV_BOOL_TEST") is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "FALSE", " Off "])
def test_the_false_set_wins_over_a_true_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("ENV_BOOL_TEST", raw)
    assert env_utils.env_bool("ENV_BOOL_TEST") is False
    assert env_utils.env_bool("ENV_BOOL_TEST", default=True) is False


def test_unset_and_blank_use_the_caller_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV_BOOL_TEST", raising=False)
    assert env_utils.env_bool("ENV_BOOL_TEST") is False
    assert env_utils.env_bool("ENV_BOOL_TEST", default=True) is True
    monkeypatch.setenv("ENV_BOOL_TEST", "  ")
    assert env_utils.env_bool("ENV_BOOL_TEST", default=True) is True


@pytest.mark.parametrize("raw", ["banana", "enabled", "onn", "TRUEISH"])
def test_unrecognised_uses_the_caller_default(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Malformed is default, the same way ``env_int`` swallows ``"x"``.

    Treating it as false re-opens the MinIO hole: a spelling that is not in
    the truth set used to force plaintext over the safe endpoint default.
    """
    monkeypatch.setenv("ENV_BOOL_TEST", raw)
    assert env_utils.env_bool("ENV_BOOL_TEST") is False
    assert env_utils.env_bool("ENV_BOOL_TEST", default=True) is True


def test_on_enables_a_factory_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMPAIGN_RUNTIME_ENABLED", "on")
    assert flags.campaign_runtime_enabled() is True


def test_minio_secure_on_enables_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    import storage

    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("MINIO_SECURE", "on")
    monkeypatch.setattr(storage, "load_env", lambda: None)
    assert storage._cfg()["secure"] is True


def test_minio_secure_false_keeps_plaintext_on_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage

    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("MINIO_SECURE", "false")
    monkeypatch.setattr(storage, "load_env", lambda: None)
    assert storage._cfg()["secure"] is False


def test_minio_secure_unset_defaults_to_tls_off_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage

    monkeypatch.setenv("MINIO_ENDPOINT", "objects.example.com:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("MINIO_SECRET_KEY", "y")
    monkeypatch.delenv("MINIO_SECURE", raising=False)
    monkeypatch.setattr(storage, "load_env", lambda: None)
    assert storage._cfg()["secure"] is True

    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    assert storage._cfg()["secure"] is False


def test_minio_secure_typo_does_not_force_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A spelling that is not in either set must not disable TLS off loopback.

    That is the original hole: ``MINIO_SECURE=on`` was set, so the unset
    default was skipped, and ``"on"`` was not in that site's tuple.
    """
    import storage

    monkeypatch.setenv("MINIO_ENDPOINT", "objects.example.com:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "x")
    monkeypatch.setenv("MINIO_SECRET_KEY", "y")
    monkeypatch.setenv("MINIO_SECURE", "onn")
    monkeypatch.setattr(storage, "load_env", lambda: None)
    assert storage._cfg()["secure"] is True

    monkeypatch.setenv("MINIO_ENDPOINT", "localhost:9000")
    assert storage._cfg()["secure"] is False


def _is_getenv(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id in {"getenv", "_env"}:
        return True
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os":
        return True
    if func.attr == "get" and isinstance(func.value, ast.Attribute):
        return func.value.attr == "environ"
    return False


def _is_env_truth_set(node: ast.expr) -> bool:
    if not isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return False
    values = {
        elt.value.lower()
        for elt in node.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    }
    return "true" in values and "yes" in values


def _application_py() -> list[Path]:
    """Every application ``.py`` under the backend, never ``.venv`` or tests."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                found.append(Path(dirpath) / name)
    return found


def _hand_rolled_env_bools() -> list[str]:
    """Functions that still parse an env flag with a private true/yes set."""
    offenders: list[str] = []
    for path in _application_py():
        rel = path.relative_to(BACKEND).as_posix()
        if rel == "env_utils.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for fn in functions:
            has_getenv = False
            has_truth_set = False
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and _is_getenv(node):
                    has_getenv = True
                if isinstance(node, ast.Compare) and any(
                    isinstance(op, (ast.In, ast.NotIn)) for op in node.ops
                ):
                    if any(_is_env_truth_set(cmp) for cmp in node.comparators):
                        has_truth_set = True
            if has_getenv and has_truth_set:
                offenders.append(f"{rel}:{fn.name}")
    return offenders


def test_application_env_booleans_go_through_env_bool() -> None:
    assert _hand_rolled_env_bools() == []
