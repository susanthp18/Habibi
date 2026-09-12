"""The TTS preview vendors and Key Vault sit behind breakers.

Their HTTP calls ran bare: a vendor that was down was retried on every
preview and every secret resolution. A transport fault counts; a rejected
key is the pool's business and does not.
"""

from __future__ import annotations

import httpx
import pytest

import circuit_breaker


@pytest.fixture(autouse=True)
def _fresh_breakers():
    for name in ("fish_tts", "openrouter_tts", "azure_key_vault"):
        circuit_breaker._breakers.pop(name, None)
    yield
    for name in ("fish_tts", "openrouter_tts", "azure_key_vault"):
        circuit_breaker._breakers.pop(name, None)


def test_fish_transport_faults_open_the_breaker(monkeypatch) -> None:
    from agent_core.providers import fish_tts, pool as pool_mod

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setattr(pool_mod, "call_with_rotation", lambda _p, fn, **_k: fn("key"))

    def _down(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _down)
    for _ in range(2):
        with pytest.raises(fish_tts.FishTTSError, match="transport error"):
            fish_tts.synthesize("hello", reference_id="v1")
    with pytest.raises(fish_tts.FishTTSError, match="unavailable"):
        fish_tts.synthesize("hello", reference_id="v1")
    assert circuit_breaker.get_breaker("fish_tts").snapshot()["state"] == "open"


def test_a_rejected_key_does_not_count_against_the_vendor(monkeypatch) -> None:
    from agent_core.providers import fish_tts, pool as pool_mod

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "1")

    def _rotation(_p, fn, **_k):
        with pytest.raises(pool_mod.KeyRejected):
            fn("dead-key")
        raise pool_mod.NoKeysAvailable("fish: no keys")

    monkeypatch.setattr(pool_mod, "call_with_rotation", _rotation)
    monkeypatch.setattr(httpx, "post", lambda *_a, **_k: httpx.Response(401, request=httpx.Request("POST", "x")))
    with pytest.raises(fish_tts.FishTTSError):
        fish_tts.synthesize("hello", reference_id="v1")
    assert circuit_breaker.get_breaker("fish_tts").snapshot()["state"] == "closed"


def test_key_vault_runs_through_its_breaker(monkeypatch) -> None:
    from agent_core.vault import persist

    monkeypatch.setenv("CIRCUIT_FAILURE_THRESHOLD", "1")
    monkeypatch.setenv("AZURE_KEY_VAULT_TOKEN", "t")
    monkeypatch.setattr(persist, "_azure_url", lambda: "https://vault.example")

    def _down(*_a, **_k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", _down)
    with pytest.raises(httpx.ConnectError):
        persist._get_azure("s1")
    with pytest.raises(circuit_breaker.CircuitOpenError):
        persist._get_azure("s1")
