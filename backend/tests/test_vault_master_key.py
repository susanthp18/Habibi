"""The vault master key comes from ``VAULT_MASTER_KEY`` and nowhere else.

``master_key`` used to read ``SKILL_PLATFORM_KEY`` as a fallback source. That
made one operator secret quietly do two unrelated jobs: signing skill packs
(the G9 publish gate) *and* sealing every connector credential in
``vault_refs.ciphertext``. Anyone entitled to the signing key could open the
vault, and rotating it after a signing incident would have left every sealed
row undecryptable — a silent one, because the sealer would happily seal new
rows under the new key while the old rows no longer opened.

Two secrets, two variables. The built-in development key stays — a laptop has
no secret store — but, as with the signing key, only where the environment says
it is not production.
"""

from __future__ import annotations

import hashlib
from importlib import import_module

import pytest

# ``agent_core.vault.__init__`` re-exports the *function* ``seal``, which
# shadows the submodule of the same name — ``from agent_core.vault import seal``
# hands back the function. Ask for the module by path.
vault_seal = import_module("agent_core.vault.seal")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither variable may leak in from the developer's shell or .env."""
    monkeypatch.delenv("VAULT_MASTER_KEY", raising=False)
    monkeypatch.delenv("SKILL_PLATFORM_KEY", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


def _digest(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


# --- no key at all ----------------------------------------------------------


@pytest.mark.parametrize("env", ["production", "prod", "staging", "PRODUCTION"])
def test_no_key_source_raises_naming_the_variable(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    with pytest.raises(RuntimeError, match="VAULT_MASTER_KEY"):
        vault_seal.master_key()


def test_the_error_tells_an_operator_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError) as excinfo:
        vault_seal.master_key()
    message = str(excinfo.value)
    assert "VAULT_MASTER_KEY" in message
    assert "SKILL_PLATFORM_KEY" not in message
    assert "production" in message


def test_sealing_in_production_without_a_key_raises_rather_than_using_the_dev_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match="VAULT_MASTER_KEY"):
        vault_seal.seal("connector-client-secret")


def test_a_laptop_still_gets_the_development_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    assert vault_seal.master_key() == _digest(vault_seal.DEV_MASTER_KEY)


# --- the skill signing key is not a vault key -------------------------------


def test_skill_platform_key_alone_is_not_used_as_the_master_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "s3cret-platform-key")
    key = vault_seal.master_key()
    assert key != _digest("s3cret-platform-key")
    assert key == _digest(vault_seal.DEV_MASTER_KEY)


def test_skill_platform_key_alone_does_not_satisfy_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is gone: a signing key set in prod no longer unlocks sealing."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "s3cret-platform-key")
    with pytest.raises(RuntimeError, match="VAULT_MASTER_KEY"):
        vault_seal.master_key()


def test_ciphertext_sealed_before_a_signing_key_rotation_still_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "vault-master")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "signing-key-v1")
    token = vault_seal.seal("connector-client-secret")

    monkeypatch.setenv("SKILL_PLATFORM_KEY", "signing-key-v2")
    assert vault_seal.open_sealed(token) == "connector-client-secret"


# --- VAULT_MASTER_KEY is used, and it is the thing that changes the key ------


def test_vault_master_key_is_used_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "the-real-vault-key")
    assert vault_seal.master_key() == _digest("the-real-vault-key")


def test_it_wins_over_a_skill_platform_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "the-real-vault-key")
    monkeypatch.setenv("SKILL_PLATFORM_KEY", "s3cret-platform-key")
    assert vault_seal.master_key() == _digest("the-real-vault-key")


def test_whitespace_only_is_not_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "   ")
    with pytest.raises(RuntimeError, match="VAULT_MASTER_KEY"):
        vault_seal.master_key()


def test_a_rotated_master_key_cannot_open_old_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a nice property — a documented one. Rotation needs a re-seal pass."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "key-v1")
    token = vault_seal.seal("connector-client-secret")

    monkeypatch.setenv("VAULT_MASTER_KEY", "key-v2")
    with pytest.raises(ValueError, match="vault_mac_mismatch"):
        vault_seal.open_sealed(token)


def test_round_trip_under_an_explicit_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("VAULT_MASTER_KEY", "the-real-vault-key")
    token = vault_seal.seal("टोकन — unicode survives")
    assert vault_seal.open_sealed(token) == "टोकन — unicode survives"
