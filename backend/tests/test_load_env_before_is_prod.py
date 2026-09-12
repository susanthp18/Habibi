"""``load_env()`` must run before ``_IS_PROD`` is decided.

Compose injects ``env_file`` before Python starts, so containers already see
``APP_ENV``. The documented bare ``uvicorn main:app`` path does not. Until
``main.py`` called ``load_env()``, ``APP_ENV=production`` sitting only in
``.env`` was invisible to the eight controls keyed off ``_IS_PROD``.

This file pins the non-container path: ``APP_ENV`` absent from the process,
present only in ``.env``, and ``_IS_PROD`` still true. The three entrypoints
that lacked the call are pinned at source so it cannot drift below the
application imports that freeze config.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _module_level_load_env_lineno(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Name) and func.id == "load_env":
                return node.lineno
    raise AssertionError(f"{path.as_posix()} has no module-level load_env() call")


def _first_import_lineno(path: Path, module: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module or alias.name.startswith(module + "."):
                    return node.lineno
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == module or node.module.startswith(module + "."):
                return node.lineno
    raise AssertionError(f"{path.as_posix()} does not import {module}")


def test_main_loads_env_before_is_prod_and_before_db() -> None:
    """The shape bot_worker.py already uses: load .env, then import db."""
    main = BACKEND / "main.py"
    load_at = _module_level_load_env_lineno(main)
    tree = ast.parse(main.read_text(encoding="utf-8"))
    is_prod_at = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_IS_PROD":
                    is_prod_at = node.lineno
    assert is_prod_at is not None, "main.py no longer assigns _IS_PROD at module level"
    assert load_at < _first_import_lineno(main, "db")
    assert load_at < is_prod_at


def test_voice_entrypoints_load_env_before_application_imports() -> None:
    """``voice/workers/insurance.py`` was the second entrypoint here.

    The mesh sidecar it belonged to is deleted — an in-process specialist hop
    does its job — so ``voice/bot.py`` is the whole voice surface again.
    """
    bot = BACKEND / "voice" / "bot.py"
    # agent_core is reached through voice.bot_flow now, so the voice import is
    # the first application import there is.
    assert _module_level_load_env_lineno(bot) < _first_import_lineno(bot, "voice")


def test_is_prod_reflects_dotenv_on_the_bare_metal_path(tmp_path: Path) -> None:
    """APP_ENV=production only in .env must set _IS_PROD. Process env is empty.

    A canary key proves the subprocess read *this* file, not backend/.env —
    whose contents this test must not observe.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=production\nWP012_CANARY=from-temp-dotenv\n",
        encoding="utf-8",
    )
    probe = f"""
import os
from pathlib import Path

# Bare metal: none of these are in the process. Credentials stay absent so
# the production boot path is a refusal, not a mode.
for key in (
    "APP_ENV",
    "WP012_CANARY",
    "API_KEY",
    "API_KEY_MAP",
    "ALLOW_UNHARDENED_PRODUCTION",
):
    os.environ.pop(key, None)

import env_loader
env_loader._ENV_FILE = Path({str(env_file)!r})
env_loader._LOADED = False

import main
import actor_context
actor_context.reload_api_key_map()
print("WP012_APP_ENV=" + main._APP_ENV)
print("WP012_IS_PROD=" + str(main._IS_PROD))
print("WP012_CANARY=" + (os.environ.get("WP012_CANARY") or ""))
try:
    main._assert_hardening_gate()
    print("WP012_HARDENING=passed")
except RuntimeError:
    print("WP012_HARDENING=refused")
has_auth = bool(
    (os.getenv("API_KEY") or "").strip() or actor_context.parse_api_key_map()
)
print("WP012_REFUSES_CREDENTIALS=" + str(main._IS_PROD and not has_auth))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = {
        line.split("=", 1)[0].removeprefix("WP012_"): line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("WP012_")
    }
    assert lines.get("CANARY") == "from-temp-dotenv"
    assert lines.get("APP_ENV") == "production"
    assert lines.get("IS_PROD") == "True"
    assert lines.get("HARDENING") == "refused"
    assert lines.get("REFUSES_CREDENTIALS") == "True"
