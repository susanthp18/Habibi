"""The seam between the provider registry and a live call.

``voice/bot.py`` constructed Azure directly, so a provider chosen in the Agent
Studio never reached a call. Closing that gap introduces a new risk in the
opposite direction: the factory is built to *fail closed*, and wiring a fatal
error onto the audio path would turn deploying the registry into an outage.

These tests pin both halves — a binding is honoured, and neither an unbound slot
nor a broken provider drops the call — plus the provenance record, without which
a fallback is indistinguishable from the thing it replaced.
"""

from __future__ import annotations

import pytest

from agent_core.providers import factory
from voice import provider_bind


class _Session:
    def __init__(self) -> None:
        self.extra: dict = {}


class _Fallback:
    """Stands in for the pre-registry Azure construction."""


class _Bound:
    pass


def _binding(provider: str = "cartesia", model: str = "sonic-3.5"):
    return factory.ResolvedBinding(
        binding_id="apb-1",
        provider_id=provider,
        kind="tts",
        model_id=model,
        service_class="x.Y",
        voice_ref=None,
        settings={},
        priority=0,
        locale="ar-AE",
        specificity=3,
    )


def _bind(monkeypatch, behaviour):
    monkeypatch.setattr(factory, "build_first_available", behaviour)
    session = _Session()
    service, prov = provider_bind.bind(
        "tts",
        tenant_id="t1",
        bot_id="b1",
        locale="ar-AE",
        session_id="VS-1",
        fallback=_Fallback,
        settings={"voice": "x"},
    )
    provider_bind.record(session, prov)
    return service, prov, session


def test_a_binding_is_honoured(monkeypatch):
    service, prov, session = _bind(monkeypatch, lambda **kw: (_Bound(), _binding()))
    assert isinstance(service, _Bound)
    assert prov["provider"] == "cartesia"
    assert prov["source"] == "binding"
    assert session.extra["providers"]["tts"]["model"] == "sonic-3.5"


def test_an_unbound_slot_falls_back_instead_of_failing(monkeypatch):
    """"This tenant has not configured a provider" is not "this locale is
    unservable". Answering it by dropping every call would make deploying the
    registry an outage."""

    def raise_unbound(**_kw):
        raise factory.NoBindingError("nothing bound")

    service, prov, _ = _bind(monkeypatch, raise_unbound)
    assert isinstance(service, _Fallback)
    assert prov == {"slot": "tts", "provider": "azure", "source": "default"}


def test_a_broken_provider_falls_back_and_records_why(monkeypatch):
    """Bound but unbuildable. Dropping a live collections call is worse than
    speaking with Azure — but the record must not claim Cartesia spoke."""

    def raise_unavailable(**_kw):
        raise factory.ProviderUnavailable("all 2 candidates failed — 429")

    service, prov, session = _bind(monkeypatch, raise_unavailable)
    assert isinstance(service, _Fallback)
    assert prov["source"] == "fallback"
    assert "429" in prov["error"]
    assert session.extra["providers"]["tts"]["provider"] == "azure"


def test_the_fallback_is_not_constructed_when_a_binding_exists(monkeypatch):
    """It is a callable, not a value: building Azure on the common path would
    open a synthesis websocket nobody uses, on every call."""
    built = []

    monkeypatch.setattr(factory, "build_first_available", lambda **kw: (_Bound(), _binding()))
    provider_bind.bind(
        "tts",
        tenant_id="t1",
        bot_id="b1",
        locale=None,
        session_id=None,
        fallback=lambda: built.append(1),
    )
    assert built == []


def test_ctor_and_settings_reach_the_factory_separately(monkeypatch):
    """text_filters is a constructor argument, not a model setting. Folding it
    into settings drops it at the Settings filter — silently, and only on the
    live audio path."""
    seen: dict = {}

    def capture(**kw):
        seen.update(kw)
        return _Bound(), _binding()

    monkeypatch.setattr(factory, "build_first_available", capture)
    provider_bind.bind(
        "tts",
        tenant_id="t1",
        bot_id="b1",
        locale=None,
        session_id=None,
        fallback=_Fallback,
        settings={"voice": "v1", "rate": "1.05"},
        ctor={"text_filters": ["f"]},
    )
    assert seen["ctor"] == {"text_filters": ["f"]}
    assert seen["voice"] == "v1" and seen["rate"] == "1.05"
    assert "text_filters" not in seen


def test_record_never_breaks_a_call():
    """Provenance is bookkeeping. It must not be able to end a conversation."""

    class Hostile:
        @property
        def extra(self):
            raise RuntimeError("boom")

    provider_bind.record(Hostile(), {"slot": "tts", "provider": "azure"})


@pytest.mark.parametrize("slot", ["stt", "tts"])
def test_both_pipeline_slots_are_supported(monkeypatch, slot):
    monkeypatch.setattr(factory, "build_first_available", lambda **kw: (_Bound(), _binding()))
    session = _Session()
    _, prov = provider_bind.bind(
        slot,
        tenant_id="t1",
        bot_id=None,
        locale=None,
        session_id=None,
        fallback=_Fallback,
    )
    provider_bind.record(session, prov)
    assert prov["slot"] == slot
    assert slot in session.extra["providers"]
