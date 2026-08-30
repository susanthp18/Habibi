"""An unconfigured deployment must not verify skill signatures against a constant.

``verify_signature`` is the G9 publish gate: a pack may attach to a published
card only if its content hash carries a valid platform signature. The key
behind that HMAC fell back to ``"dev-skill-platform-key-not-for-prod"`` — a
literal in this repository — whenever ``SKILL_PLATFORM_KEY`` was unset.

A production deploy that simply forgot the variable therefore accepted any
signature an attacker could compute from public source, which is the same as
having no gate. The fallback is still right for a laptop, so the fix is not to
remove it but to require the environment to *say* it is not production.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from agent_core.skills import sign


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither variable may leak in from the developer's shell or .env."""
    monkeypatch.delenv("SKILL_PLATFORM_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


def _expected(key: str, content_hash: str) -> str:
    return hmac.new(key.encode("utf-8"), content_hash.encode("utf-8"), hashlib.sha256).hexdigest()


# --- missing key, production ------------------------------------------------


@pytest.mark.parametrize("env", ["production", "prod", "PRODUCTION", " Production "])
def test_missing_key_in_production_raises(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.platform_key()


def test_the_error_names_the_variable_an_operator_has_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError) as excinfo:
        sign.platform_key()
    message = str(excinfo.value)
    assert "SKILL_PLATFORM_KEY" in message
    assert "production" in message


def test_an_unrecognised_environment_is_treated_as_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``staging`` is not on the allow-list, and a typo must not open the gate."""
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.platform_key()
    monkeypatch.setenv("APP_ENV", "dvelopment")
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.platform_key()


def test_verification_raises_rather_than_quietly_accepting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate itself, not just the key helper — it must not return ``True``."""
    monkeypatch.setenv("APP_ENV", "production")
    forged = _expected(sign.DEV_PLATFORM_KEY, "abc")
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.verify_signature("abc", forged)
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.sign_hash("abc")


def test_an_empty_or_whitespace_key_is_not_a_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "   ")
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.platform_key()


# --- missing key, development -----------------------------------------------


@pytest.mark.parametrize("env", ["dev", "development", "local", "test", "sandbox", "ci", "DEV"])
def test_missing_key_in_a_declared_non_prod_env_uses_the_dev_key(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    assert sign.platform_key() == sign.DEV_PLATFORM_KEY.encode("utf-8")


def test_an_unset_app_env_still_means_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matches ``main.py``: no ``APP_ENV`` is a laptop, and the suite runs there."""
    assert sign.platform_key() == sign.DEV_PLATFORM_KEY.encode("utf-8")
    digest = sign.sign_hash("abc")
    assert sign.verify_signature("abc", digest)


def test_env_is_read_as_a_fallback_for_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(RuntimeError, match="SKILL_PLATFORM_KEY"):
        sign.platform_key()


# --- key configured ---------------------------------------------------------


@pytest.mark.parametrize("env", ["production", "dev"])
def test_a_configured_key_is_the_one_used(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "s3cret-platform-key")

    assert sign.platform_key() == b"s3cret-platform-key"
    assert sign.sign_hash("abc") == _expected("s3cret-platform-key", "abc")
    assert sign.verify_signature("abc", sign.sign_hash("abc"))


def test_a_signature_forged_with_the_dev_key_fails_against_a_real_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point: the committed constant must buy an attacker nothing."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "s3cret-platform-key")
    forged = _expected(sign.DEV_PLATFORM_KEY, "abc")
    assert not sign.verify_signature("abc", forged)
