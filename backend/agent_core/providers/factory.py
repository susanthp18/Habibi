"""Binding → a live Pipecat service. The one place a provider is chosen.

``voice/bot.py`` used to construct ``AzureSTTService`` directly, and
``voice/tuning_apply.py`` resolved a locale with ``.get(key, Language.EN_IN)``.
The combination meant an unmapped locale did not fail — it transcribed with an
English-India recogniser and returned fluent nonsense that every downstream
layer then scored as if it were the caller's words.

This module replaces both. Two properties matter more than the plumbing:

**Resolution is explicit, and its absence is an error.**
:func:`resolve_chain` returns candidates most-specific-first and returns an
*empty* list when nothing is bound. :func:`build_stt` raises rather than
substituting a default, because the substituted default is the original bug.

**The chain is a failover, not a preference list.**
``priority`` orders candidates within one specificity so an exhausted free-tier
key falls through to the next provider instead of dropping the call. That is why
the caller gets a list and walks it, rather than getting one answer.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

import db
from agent_core.providers import pool as pool_mod
from agent_core.providers.registry import SEED_BY_SLUG

logger = logging.getLogger(__name__)


class NoBindingError(RuntimeError):
    """Nothing is bound for this (bot, slot, locale) and there is no default.

    Deliberately fatal. The multilingual design's rule is *fail closed, loudly*:
    an unservable locale becomes a routed ``language_unsupported`` event and a
    human handoff, never a silent substitution.
    """


class ProviderUnavailable(RuntimeError):
    """Every candidate in the chain failed to build."""


@dataclass(frozen=True)
class ResolvedBinding:
    binding_id: str
    provider_id: str
    kind: str
    model_id: str
    service_class: str
    voice_ref: str | None
    settings: dict[str, Any]
    priority: int
    locale: str | None
    specificity: int


def settings_field_names(settings_cls: Any) -> frozenset[str]:
    """The setting names a provider's ``Settings`` class actually declares.

    This exists because the obvious version of it was wrong and the wrongness
    was invisible. ``build`` filtered with ``getattr(cls, "model_fields", {})``
    — a pydantic idiom — and Pipecat 1.6.0's Settings classes are *dataclasses*.
    So the lookup returned ``{}`` on every provider, the ``if not allowed``
    guard read that as "unknown class, pass everything through", and a filter
    whose whole purpose was to stop an undeclared kwarg reaching a constructor
    passed every key untouched for as long as it has existed.

    Nothing depended on it while the only settings in play were Azure's own, so
    it stayed a no-op nobody could see. It stops being invisible the moment a
    card can carry provider-specific params: a Fish ``temperature`` arriving at
    ``AzureTTSSettings.__init__`` is a ``TypeError`` in the middle of pipeline
    construction, which drops the call rather than the setting.

    Three shapes, in order: pydantic v2, dataclass, then the ``__init__``
    signature. An empty result means "could not tell" and callers must fall back
    to passing everything — refusing to construct a service because this
    function did not recognise its Settings class would be worse than the bug.
    """
    if settings_cls is None:
        return frozenset()

    fields = getattr(settings_cls, "model_fields", None)
    if isinstance(fields, dict) and fields:
        return frozenset(fields)

    if dataclasses.is_dataclass(settings_cls):
        return frozenset(f.name for f in dataclasses.fields(settings_cls))

    try:
        params = inspect.signature(settings_cls).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic callable
        return frozenset()
    return frozenset(
        name
        for name, p in params.items()
        if name != "self" and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    )


def _import_class(path: str) -> type:
    """'a.b.C' → C. Raises ImportError with the path in the message."""
    module_path, _, cls_name = path.rpartition(".")
    if not module_path:
        raise ImportError(f"service_class is not fully qualified: {path!r}")
    module = importlib.import_module(module_path)
    try:
        return getattr(module, cls_name)
    except AttributeError as exc:  # pragma: no cover - config error
        raise ImportError(f"{module_path} has no attribute {cls_name!r}") from exc


def resolve_chain(
    *,
    tenant_id: str,
    slot: str,
    bot_id: str | None = None,
    locale: str | None = None,
) -> list[ResolvedBinding]:
    """Candidate bindings, most specific first, then by ascending priority.

    Specificity, highest wins:
      3 = this bot + this locale
      2 = this bot, any locale
      1 = tenant default + this locale
      0 = tenant default, any locale
    """
    sql = text(
        """
        SELECT
          b.id            AS binding_id,
          m.provider_id   AS provider_id,
          m.kind          AS kind,
          m.model_id      AS model_id,
          m.service_class AS service_class,
          b.voice_ref     AS voice_ref,
          b.settings      AS settings,
          b.priority      AS priority,
          b.locale        AS locale,
          (CASE WHEN b.bot_id IS NOT NULL THEN 2 ELSE 0 END
           + CASE WHEN b.locale IS NOT NULL THEN 1 ELSE 0 END) AS specificity
        FROM agent_provider_bindings b
        JOIN provider_models m ON m.id = b.provider_model_id
        WHERE b.tenant_id = :tenant_id
          AND b.slot = :slot
          AND b.enabled
          AND m.enabled
          AND (b.bot_id IS NULL OR b.bot_id = :bot_id)
          AND (b.locale IS NULL OR b.locale = :locale)
        ORDER BY specificity DESC, b.priority ASC
        """
    )
    with db.engine.connect() as conn:
        rows = conn.execute(
            sql, {"tenant_id": tenant_id, "slot": slot, "bot_id": bot_id, "locale": locale}
        ).mappings().all()

    return [
        ResolvedBinding(
            binding_id=r["binding_id"],
            provider_id=r["provider_id"],
            kind=r["kind"],
            model_id=r["model_id"],
            service_class=r["service_class"],
            voice_ref=r["voice_ref"],
            settings=dict(r["settings"] or {}),
            priority=int(r["priority"]),
            locale=r["locale"],
            specificity=int(r["specificity"]),
        )
        for r in rows
    ]


def _credentials(provider_id: str, session_id: str | None, tenant_id: str | None) -> dict[str, Any]:
    """Constructor kwargs carrying this provider's credentials.

    Shapes differ per vendor — Azure wants ``api_key`` plus ``region``, the rest
    want ``api_key`` alone — so the difference is encoded here rather than in
    every call site.
    """
    import os

    spec = SEED_BY_SLUG.get(provider_id)
    if spec is None or spec.key_env is None:
        return {}

    key = pool_mod.get_pool(provider_id).acquire(session_id, tenant_id=tenant_id)
    creds: dict[str, Any] = {"api_key": key}
    if provider_id == "azure":
        creds["region"] = os.getenv("AZURE_SPEECH_REGION") or "eastus2"
    return creds


def build(
    binding: ResolvedBinding,
    *,
    session_id: str | None = None,
    tenant_id: str | None = None,
    ctor: dict[str, Any] | None = None,
    **overrides: Any,
) -> Any:
    """Instantiate the Pipecat service for one binding.

    ``overrides`` are merged over the binding's stored ``settings`` — the
    caller's live values (a mid-call language switch, a tuning slider) win over
    what was configured at publish time.

    ``ctor`` is for arguments that are *not* settings: ``text_filters``,
    ``ttfs_p99_latency``, ``text_aggregation_mode``. They are constructor
    parameters rather than model settings, so folding them into ``overrides``
    would drop them at the Settings filter below — silently, and only on the
    live audio path, which is the worst place to discover a missing text filter.
    """
    cls = _import_class(binding.service_class)
    settings = {**binding.settings, **overrides}
    if binding.voice_ref and "voice" not in settings:
        settings["voice"] = binding.voice_ref

    kwargs = _credentials(binding.provider_id, session_id, tenant_id)
    kwargs.update(ctor or {})
    settings_cls = getattr(cls, "Settings", None)
    if settings_cls is not None and settings:
        # Only pass keys this service actually declares; providers disagree on
        # setting names and an unknown kwarg is a TypeError at call time.
        # See `settings_field_names` for why this is not a `model_fields` read.
        allowed = settings_field_names(settings_cls)
        filtered = {k: v for k, v in settings.items() if not allowed or k in allowed}
        dropped = sorted(set(settings) - set(filtered))
        if dropped:
            logger.debug(
                "dropped unsupported settings · provider=%s · model=%s · keys=%s",
                binding.provider_id,
                binding.model_id,
                dropped,
            )
        kwargs["settings"] = settings_cls(**filtered)
    return cls(**kwargs)


def build_first_available(
    *,
    tenant_id: str,
    slot: str,
    bot_id: str | None = None,
    locale: str | None = None,
    session_id: str | None = None,
    ctor: dict[str, Any] | None = None,
    **overrides: Any,
) -> tuple[Any, ResolvedBinding]:
    """Walk the chain and return the first service that constructs.

    Raises :class:`NoBindingError` when nothing is bound — never substitutes a
    default — and :class:`ProviderUnavailable` when every candidate failed.
    """
    chain = resolve_chain(tenant_id=tenant_id, slot=slot, bot_id=bot_id, locale=locale)
    if not chain:
        raise NoBindingError(
            f"no {slot} provider bound for tenant={tenant_id} bot={bot_id} locale={locale}"
        )

    errors: list[str] = []
    for candidate in chain:
        try:
            service = build(
                candidate,
                session_id=session_id,
                tenant_id=tenant_id,
                ctor=ctor,
                **overrides,
            )
        except pool_mod.NoKeysAvailable as exc:
            errors.append(f"{candidate.provider_id}: {exc}")
            logger.warning("provider skipped, no keys · %s", exc)
            continue
        except Exception as exc:  # noqa: BLE001 - any construction failure fails over
            errors.append(f"{candidate.provider_id}: {exc}")
            logger.exception(
                "provider build failed · provider=%s · model=%s",
                candidate.provider_id,
                candidate.model_id,
            )
            continue

        logger.info(
            "provider bound · slot=%s · provider=%s · model=%s · locale=%s · specificity=%d",
            slot,
            candidate.provider_id,
            candidate.model_id,
            locale,
            candidate.specificity,
        )
        return service, candidate

    raise ProviderUnavailable(f"{slot}: all {len(chain)} candidates failed — {'; '.join(errors)}")
