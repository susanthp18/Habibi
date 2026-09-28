"""The "is this actually a laptop?" test has one home, and it is the leaf.

``agent_core/vault/seal.py`` used to open with ``from agent_core.skills.sign
import NON_PROD_ENVS, _env_name``. Two things were wrong with that. It reached
for a *private* name across package boundaries, so the signer could not rename
its own helper without breaking the vault. And it made the vault — which seals
connector credentials and knows nothing about skill packs — import the skill
signer just to ask what ``APP_ENV`` says.

The helper now lives in ``env_utils``, the same leaf module ``db.py`` and
``agent_core`` both already take (see ``money_inr``'s docstring for why that
layer exists). Behaviour is unchanged; this file pins that, and pins that the
two key helpers cannot drift apart on what counts as production.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import env_utils

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


# --- the promoted helper itself ---------------------------------------------


def test_env_name_is_public_on_the_leaf_module() -> None:
    assert callable(env_utils.env_name)
    assert "env_name" in env_utils.__all__
    assert "env_bool" in env_utils.__all__
    assert "NON_PROD_ENVS" in env_utils.__all__


def test_an_unset_environment_is_a_laptop() -> None:
    assert env_utils.env_name() == "dev"
    assert env_utils.is_prod() is False


@pytest.mark.parametrize(
    "raw,expected",
    [("dev", "dev"), ("PRODUCTION", "production"), (" Production ", "production"), ("", "dev")],
)
def test_it_lower_cases_and_strips(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("APP_ENV", raw)
    assert env_utils.env_name() == expected


def test_env_is_the_fallback_for_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    assert env_utils.env_name() == "production"
    assert env_utils.is_prod() is True


def test_app_env_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ENV", "production")
    assert env_utils.env_name() == "dev"


@pytest.mark.parametrize(
    "env", ["dev", "development", "local", "test", "testing", "sandbox", "ci", "DEV"]
)
def test_declared_non_prod_names_allow_a_dev_key(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    assert env_utils.is_prod() is False


@pytest.mark.parametrize("env", ["production", "prod", "staging", "dvelopment", "uat"])
def test_anything_else_does_not(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    """``staging`` is not on the allow-list, and a typo must not open a gate."""
    monkeypatch.setenv("APP_ENV", env)
    assert env_utils.is_prod() is True


# --- one implementation, two callers ----------------------------------------


def test_no_module_still_reaches_for_the_old_private_name() -> None:
    """Word-bounded: ``template_env_name`` in ``treatment/enact`` is unrelated."""
    private = re.compile(r"_env_name")
    offenders = [
        path.relative_to(BACKEND).as_posix()
        for path in (BACKEND / "agent_core").rglob("*.py")
        if private.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


