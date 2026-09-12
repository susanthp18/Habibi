"""G15 and G17: the voice the card wears, against the languages it claims and
the vendors it can speak through. ``gate`` is the compiler's registered
constructor, passed in so this module does not import the compiler."""

from __future__ import annotations

from typing import Any, Callable

def _primary_subtag(tag: str) -> str:
    """``en-IN`` and ``en`` are the same language to this gate.

    Only Azure publishes region-qualified locales. Every other provider the
    registry syncs carries a bare language code — Fish's Arabic rows are ``ar``,
    not ``ar-EG`` — so comparing whole tags would warn on every non-Azure voice
    a card legitimately uses, which is the fastest way to teach an operator to
    ignore the warning.
    """
    return (tag or "").strip().replace("_", "-").split("-")[0].casefold()


def voice_locale_gate(
    short_name: str | None,
    voice_locale: str | None,
    card_locales: list[str] | None,
    *,
    gate: Callable[..., Any],
) -> Any:
    """G15 — the voice speaks a language the card does not claim.

    A warning, never a block. Shipping a voice from outside the card's language
    set is a legitimate localisation override, and a gate that refused it would
    be wrong more often than right. Silence was the defect: a kaia draft carried
    an Arabic Fish voice on an en-IN collections card, cleared G0-G14, and left
    Publish enabled — one click from an English collections bot speaking Arabic.
    """
    sn = (short_name or "").strip()
    wanted = [t for t in (card_locales or []) if t]
    if not sn or not wanted:
        return gate("G15", "voice_locale", "skipped", "no voice or no card language")
    spoken = (voice_locale or "").strip()
    if not spoken:
        # Not this gate's story to tell. An id the catalog cannot resolve is
        # already reported by get_tts_voice_warning, and what the runtime then
        # speaks is the fallback voice, whose locale is not the stored id's.
        return gate("G15", "voice_locale", "skipped", f"{sn} is not in the voice catalog")
    if spoken == "und":
        # The sync could not tell what this voice speaks (a multilingual or
        # unlabelled catalogue row). Unknown is not a mismatch; warning on it
        # taught operators the gate cries wolf.
        return gate("G15", "voice_locale", "skipped", f"{sn} has no language on record")
    if _primary_subtag(spoken) in {_primary_subtag(t) for t in wanted}:
        return gate("G15", "voice_locale", "pass", f"{spoken} within {', '.join(wanted)}")
    return gate(
        "G15",
        "voice_locale",
        "warn",
        f"voice speaks {spoken}, card speaks {', '.join(wanted)}",
        [{"voice": sn, "voiceLocale": spoken, "cardLocales": wanted}],
    )


def voice_provider_gate(
    short_name: str | None,
    voice_provider: str | None,
    bound_providers: set[str] | frozenset[str] | None,
    *,
    gate: Callable[..., Any],
) -> Any:
    """G17 — the voice's vendor is one this bot can actually speak through.

    Unlike G15 this blocks, because the failure is a dropped call rather than a
    wrong language. The catalog namespaces every non-Azure voice as
    ``{provider}:{ref}``, so a card can name ``fish:abc`` while the only bound
    TTS provider is Azure. Nothing catches that today: ``build_with_failover``
    only retries on *construction* errors, and a voice name is a string every
    service accepts at construction — it fails at synthesis, on the first
    utterance, after the customer has been dialled.

    Skips rather than guesses in all three unknown cases: no voice, a voice the
    catalog cannot resolve (``get_tts_voice_warning`` already owns that story,
    and the runtime speaks a fallback whose provider is not the stored id's),
    and a caller that could not determine the bindings.
    """
    sn = (short_name or "").strip()
    if not sn:
        return gate("G17", "voice_provider_bound", "skipped", "no voice")
    if not voice_provider:
        return gate("G17", "voice_provider_bound", "skipped", f"{sn} is not in the voice catalog")
    if bound_providers is None:
        return gate("G17", "voice_provider_bound", "skipped", "tts bindings unavailable")
    if not bound_providers:
        # Nothing bound at all is NoBindingError's story, and voice/bot.py still
        # has an Azure fallback lambda — so this gate has no opinion.
        return gate("G17", "voice_provider_bound", "skipped", "no tts provider bound")
    if voice_provider in bound_providers:
        return gate("G17", "voice_provider_bound", "pass", f"{voice_provider} is bound")
    return gate(
        "G17",
        "voice_provider_bound",
        "fail",
        f"voice needs {voice_provider}, bound: {', '.join(sorted(bound_providers))}",
        [{"voice": sn, "voiceProvider": voice_provider, "boundProviders": sorted(bound_providers)}],
    )
