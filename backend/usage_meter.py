"""Live usage metering → usage_events → billing_usage_daily.

Records billable Azure OpenAI / Speech units at call time using env-driven
USD list prices converted to INR. Daily facts are upserted so /billing reads
real spend instead of synthetic seed burn.
"""

from __future__ import annotations

import atexit
import contextvars
import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text

from env_loader import load_env
from env_utils import NON_PROD_ENVS, env_float, env_int

logger = logging.getLogger(__name__)

# Azure list prices (USD) — overridable via env. Defaults match public PAYG rates
# for the deployments this app uses (chat mini-class + text-embedding-3-small +
# Speech neural TTS / standard STT). See Azure OpenAI / Speech pricing pages.
_DEFAULTS = {
    "USD_INR_FX": "86.0",
    # Chat: GPT-5-mini / gpt-4o-mini class — $ / 1M tokens
    "PRICE_CHAT_INPUT_USD_PER_1M": "0.25",
    "PRICE_CHAT_OUTPUT_USD_PER_1M": "2.00",
    # Embeddings: text-embedding-3-small — $ / 1M tokens
    "PRICE_EMBED_USD_PER_1M": "0.02",
    # Azure Speech neural TTS — $ / 1M characters
    "PRICE_TTS_USD_PER_1M_CHARS": "15.0",
    # Azure Speech standard STT — $ / hour → we bill per minute
    "PRICE_STT_USD_PER_HOUR": "1.0",
}

SERVICE_CHAT = "llm_chat"
SERVICE_EMBED = "llm_embed"
SERVICE_STT = "stt_az"
SERVICE_TTS = "tts_az"


_MILLION = Decimal(1_000_000)
# Two different scales, because the columns differ and conflating them loses
# money. ``usage_events.cost_inr`` and ``billing_usage_daily.cost_inr`` are
# numeric(14,6); ``billing_services.unit_cost_inr`` is numeric(14,4).
#
# Both used to quantize at 4dp. A single small charge — 10 embedding tokens is
# ~0.0000172 INR — then rounded to exactly zero *before* it reached the
# database, so the event recorded usage with no cost at all. Metering per-token
# work at a scale coarser than the per-token price is self-defeating.
_EVENT_QUANT = Decimal("0.000001")
_PRICE_BOOK_QUANT = Decimal("0.0001")


def _quantize_event_money(value: Decimal) -> Decimal:
    """Round to the 6dp the usage/rollup cost columns store."""
    return value.quantize(_EVENT_QUANT, rounding=ROUND_HALF_UP)


def _quantize_money(value: Decimal) -> Decimal:
    """Round to the 4dp ``billing_services.unit_cost_inr`` stores."""
    return value.quantize(_PRICE_BOOK_QUANT, rounding=ROUND_HALF_UP)


def _env_decimal(name: str) -> Decimal:
    """Price/FX lookup as Decimal.

    Money is never computed in binary floating point here: these values feed
    numeric(14,4) columns and are summed across millions of events, where float
    representation error accumulates into a real billing discrepancy.
    """
    load_env()
    raw = (os.getenv(name) or _DEFAULTS.get(name) or "0").strip()
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal(_DEFAULTS.get(name, "0"))


def fx_rate_decimal() -> Decimal:
    return max(Decimal(1), _env_decimal("USD_INR_FX"))


def chat_cost_inr(*, prompt_tokens: int, completion_tokens: int) -> Decimal:
    fx = fx_rate_decimal()
    pin = _env_decimal("PRICE_CHAT_INPUT_USD_PER_1M")
    pout = _env_decimal("PRICE_CHAT_OUTPUT_USD_PER_1M")
    usd = (Decimal(int(prompt_tokens)) / _MILLION) * pin + (
        Decimal(int(completion_tokens)) / _MILLION
    ) * pout
    return usd * fx


def embed_cost_inr(*, prompt_tokens: int) -> Decimal:
    p = _env_decimal("PRICE_EMBED_USD_PER_1M")
    return (Decimal(int(prompt_tokens)) / _MILLION) * p * fx_rate_decimal()


def tts_cost_inr(*, chars: int) -> Decimal:
    p = _env_decimal("PRICE_TTS_USD_PER_1M_CHARS")
    return (Decimal(int(chars)) / _MILLION) * p * fx_rate_decimal()


def stt_cost_inr(*, minutes: float) -> Decimal:
    p = _env_decimal("PRICE_STT_USD_PER_HOUR")
    return (_to_decimal(minutes) / Decimal(60)) * p * fx_rate_decimal()


def _to_decimal(value: Any) -> Decimal:
    # NaN / Infinity survive Decimal(str(...)) and would reach the
    # numeric(14,4) INSERT — a quantity that cannot be stored, and that poisons
    # every sum it is added to on the way there.
    if isinstance(value, Decimal):
        return value if value.is_finite() else Decimal(0)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)
    return parsed if parsed.is_finite() else Decimal(0)


def unit_cost_book_inr() -> dict[str, dict[str, Any]]:
    """Catalog rows for billing_services — INR unit costs derived from USD list × FX.

    Decimal throughout: these values are written to ``billing_services.unit_cost_inr``
    (numeric) and multiplied by usage to produce invoice lines, so binary float
    rounding here becomes a money discrepancy downstream.
    """
    fx = fx_rate_decimal()
    # Blended chat display rate assumes ~70% input / 30% output mix.
    pin = _env_decimal("PRICE_CHAT_INPUT_USD_PER_1M")
    pout = _env_decimal("PRICE_CHAT_OUTPUT_USD_PER_1M")
    thousand = Decimal(1000)
    chat_per_1k_usd = ((Decimal("0.7") * pin) + (Decimal("0.3") * pout)) / thousand
    embed_per_1k_usd = _env_decimal("PRICE_EMBED_USD_PER_1M") / thousand
    tts_per_1k_usd = _env_decimal("PRICE_TTS_USD_PER_1M_CHARS") / thousand
    stt_per_min_usd = _env_decimal("PRICE_STT_USD_PER_HOUR") / Decimal(60)
    return {
        SERVICE_CHAT: {
            "name": "Azure OpenAI Chat",
            "provider": "Azure",
            "category": "LLM",
            "unit": "1K tokens",
            "unit_cost_inr": _quantize_money(chat_per_1k_usd * fx),
            "color": "#3b82f6",
        },
        SERVICE_EMBED: {
            "name": "Azure OpenAI Embeddings",
            "provider": "Azure",
            "category": "LLM",
            "unit": "1K tokens",
            "unit_cost_inr": _quantize_money(embed_per_1k_usd * fx),
            "color": "#6366f1",
        },
        SERVICE_STT: {
            "name": "Azure Speech STT",
            "provider": "Azure",
            "category": "Voice",
            "unit": "minute",
            "unit_cost_inr": _quantize_money(stt_per_min_usd * fx),
            "color": "#0ea5e9",
        },
        SERVICE_TTS: {
            "name": "Azure Speech TTS",
            "provider": "Azure",
            "category": "Voice",
            "unit": "1K chars",
            "unit_cost_inr": _quantize_money(tts_per_1k_usd * fx),
            "color": "#14b8a6",
        },
    }


def estimate_stt_minutes(audio_bytes: int, content_type: str | None = None) -> float:
    """Rough duration from compressed audio size when Azure simple STT omits Duration."""
    if audio_bytes <= 0:
        return 0.01
    ct = (content_type or "").lower()
    # Opus/webm ~16 kbps ≈ 2000 B/s; wav 16kHz mono 16-bit ≈ 32000 B/s
    if "wav" in ct or "wave" in ct or "pcm" in ct:
        seconds = audio_bytes / 32000.0
    else:
        seconds = audio_bytes / 2000.0
    return max(0.01, round(seconds / 60.0, 4))


def _engine():
    import db as dbmod

    return dbmod.engine


def _tenant_id() -> str:
    # Was a second, independent read of the environment. It carried a comment
    # explaining that without load_env() a TENANT_ID defined only in .env would
    # silently meter to the default tenant — correct, and true of `db` as well,
    # which is the half that was actually wrong. `db` now reads .env for this
    # key too, so metering and querying cannot name different tenants.
    import db

    return db.current_tenant()


# --- Ambient call attribution ----------------------------------------------
# chat_with_tools() / embed_texts() / synthesize() are generic utilities called
# from deep, varied stacks (WhatsApp job worker, KB retrieval, sandbox runs).
# Threading an interaction_id parameter down every one of those paths would
# touch a lot of unrelated signatures and silently lose attribution wherever a
# caller was missed. A context variable scopes it at the boundary instead: set
# it once where the interaction is known and every nested meter call inherits it.
#
# contextvars are per-thread and per-task, and asyncio.to_thread copies the
# context, so this is correct across both the async request path and the
# to_thread work the CRM sink does. An explicit interaction_id argument always
# wins over the ambient one.
_current_interaction: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "usage_meter_interaction", default=None
)


@contextmanager
def attribute_to(interaction_id: str | None) -> Iterator[None]:
    """Attribute usage metered inside this block to ``interaction_id``."""
    token = _current_interaction.set(interaction_id or None)
    try:
        yield
    finally:
        _current_interaction.reset(token)


def retarget_attribution(interaction_id: str | None) -> None:
    """Point the *current* attribution scope at an interaction.

    For entry points that only learn which interaction they are serving partway
    through their work (a job worker has to load the conversation first). Open an
    ``attribute_to(None)`` scope at the boundary and call this once the id is
    known; the enclosing scope's exit still restores the previous value, so this
    cannot leak attribution into the next job on the same thread.
    """
    _current_interaction.set(interaction_id or None)


def current_interaction_id() -> str | None:
    return _current_interaction.get()


# Not ``env_utils.NON_PROD_ENVS``, and the difference is the point.
#
# That allow-list answers "may this box fall back to the dev key committed in
# this repository?", and it counts ``test``/``testing``/``ci`` as non-production.
# Billing asks a different question, about a different column. A CI box that
# meters a real Azure call has spent real money; filing that spend under
# ``sandbox`` hides it from the production invoice, where the whole point of
# ``usage_events`` is that /billing reads metered spend instead of synthetic
# seed burn. So the billing bucket is the shared list minus the three names
# that mean "a machine running the suite" rather than "a sandbox tenant".
#
# Deriving it by subtraction rather than restating the four names keeps the
# relationship visible: if ``NON_PROD_ENVS`` grows a name, this bucket grows it
# too unless someone comes here and says why not.
_SANDBOX_BILLING_ENVS = NON_PROD_ENVS - {"test", "testing", "ci"}


def _billing_env() -> str:
    """The billing environment: exactly ``production`` or ``sandbox``.

    Deliberately *not* :func:`env_utils.env_name`, which was promoted for the
    signing-key/vault question. This is a two-valued money column, not a
    free-form environment name — ``db._BILLING_ENVS`` rejects anything else, so
    an APP_ENV of ``staging`` has to land on one side or the other here rather
    than reaching the database as itself.

    It also differs on the two inputs the shared helper cannot express:
    ``BILLING_ENV`` wins over ``APP_ENV``, so a sandbox tenant can be metered
    separately from the app's own environment; and an environment that says
    nothing at all bills as ``production``, where the shared helper assumes a
    laptop. Those defaults point opposite ways on purpose. Guessing "laptop"
    costs an unsigned artifact; guessing "sandbox" costs an invoice line that
    silently never appears.
    """
    load_env()
    raw = (os.getenv("BILLING_ENV") or os.getenv("APP_ENV") or "production").strip().lower()
    return "sandbox" if raw in _SANDBOX_BILLING_ENVS else "production"


# --- Buffered write path ---------------------------------------------------
# Every LLM / TTS / STT call used to do two synchronous writes inside the
# request (or the live audio pipeline). Events are now buffered in-process and
# flushed in batches by a background thread, so metering adds no database
# round-trip to the caller's latency.
# Resolved lazily through load_env(), like every other setting in this module:
# reading them at import time ignored .env entirely and made a malformed value
# an ImportError that took the whole app down instead of falling back.


def _flush_max_events() -> int:
    load_env()
    return max(1, env_int("USAGE_METER_FLUSH_MAX_EVENTS", 200))


def _flush_interval_s() -> float:
    load_env()
    return max(1.0, env_float("USAGE_METER_FLUSH_INTERVAL_S", 5.0))


def _buffer_max_events() -> int:
    """Hard ceiling so a sustained database outage cannot grow the buffer
    without bound; oldest events are dropped (with a log) rather than
    exhausting memory."""
    load_env()
    return max(_flush_max_events(), env_int("USAGE_METER_BUFFER_MAX", 5000))

_buffer: list[dict[str, Any]] = []
_buffer_lock = threading.Lock()
_flusher: threading.Thread | None = None
_flusher_lock = threading.Lock()
_flush_now = threading.Event()
_shutdown = threading.Event()


def start() -> None:
    """Re-arm metering after :func:`shutdown`.

    ``_shutdown`` is process-global, so once it is set every later
    ``record_usage`` spawned a flusher thread whose loop exited on its first
    condition check — thread churn with no flushing. A lifecycle that comes
    back up has to clear the flag explicitly.
    """
    _shutdown.clear()
    _ensure_flusher()


def _ensure_flusher() -> None:
    global _flusher

    if _shutdown.is_set():
        # Metering is stopped: do not spawn a worker that would exit at once.
        return
    if _flusher is not None and _flusher.is_alive():
        return
    with _flusher_lock:
        if _shutdown.is_set():
            return
        if _flusher is not None and _flusher.is_alive():
            return
        _flusher = threading.Thread(
            target=_flush_loop, name="usage-meter-flush", daemon=True
        )
        _flusher.start()


def _flush_loop() -> None:
    while not _shutdown.is_set():
        _flush_now.wait(timeout=_flush_interval_s())
        _flush_now.clear()
        try:
            flush()
        except Exception:
            logger.exception("usage_meter_flush_loop_error")


def record_usage(
    *,
    service_id: str,
    units: float | Decimal,
    cost_inr: float | Decimal,
    meta: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    environment: str | None = None,
    occurred_at: datetime | None = None,
    source_ref: str | None = None,
    interaction_id: str | None = None,
    model: str | None = None,
) -> None:
    """Buffer a usage event; the flusher persists it in batches.

    ``interaction_id`` attributes the spend to a call and ``model`` to a
    deployment. Both are nullable: batch and maintenance paths have no call, and
    an unattributed event is still correct spend — it just cannot be drilled
    into. Neither participates in the daily rollup key.
    """
    units_d = _to_decimal(units)
    # Quantize to what usage_events.cost_inr / billing_usage_daily.cost_inr can
    # actually hold, numeric(14,6). Buffering the full-precision value let the
    # per-event INSERT round while the daily rollup summed the unrounded figures
    # in Python — so SUM(usage_events) and billing_usage_daily disagreed by a
    # fraction per event, and the invoice never reconciled.
    cost_d = _quantize_event_money(_to_decimal(cost_inr))
    if units_d <= 0 and cost_d <= 0:
        return
    tid = tenant_id or _tenant_id()
    env = environment or _billing_env()
    when = occurred_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    event = {
        "id": f"ue-{uuid.uuid4().hex[:16]}",
        "tenant_id": tid,
        "environment": env,
        "service_id": service_id,
        "units": units_d,
        "cost_inr": cost_d,
        "meta": json.dumps(meta or {}),
        "occurred_at": when,
        "source_ref": source_ref,
        # Explicit wins; otherwise inherit whatever boundary we are running under.
        "interaction_id": (interaction_id or _current_interaction.get() or None),
        "model": (model or None),
    }

    with _buffer_lock:
        _buffer.append(event)
        overflow = len(_buffer) - _buffer_max_events()
        if overflow > 0:
            del _buffer[:overflow]
            logger.error("usage_meter_buffer_overflow dropped=%s", overflow)
        should_flush = len(_buffer) >= _flush_max_events()

    _ensure_flusher()
    if should_flush:
        _flush_now.set()


def flush() -> int:
    """Persist buffered usage events. Returns the number of events written."""
    with _buffer_lock:
        if not _buffer:
            return 0
        batch = list(_buffer)
        _buffer.clear()

    # Aggregate per (service, tenant, env, day) so a burst produces one daily
    # upsert instead of one per event.
    daily: dict[tuple[str, str, str, date], dict[str, Decimal]] = {}
    for event in batch:
        key = (
            event["service_id"],
            event["tenant_id"],
            event["environment"],
            event["occurred_at"].date(),
        )
        acc = daily.setdefault(key, {"units": Decimal(0), "cost_inr": Decimal(0)})
        acc["units"] += event["units"]
        acc["cost_inr"] += event["cost_inr"]

    try:
        with _engine().begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO usage_events (
                      id, tenant_id, environment, service_id, units, cost_inr,
                      meta, occurred_at, source_ref, interaction_id, model
                    ) VALUES (
                      :id, :tenant_id, :environment, :service_id, :units, :cost_inr,
                      CAST(:meta AS jsonb), :occurred_at, :source_ref,
                      -- Resolve through the PK rather than binding the id
                      -- directly: an interaction that never materialised (a
                      -- sandbox session whose row failed) or that a retention
                      -- sweep removed mid-flush would raise a foreign-key
                      -- violation, which _is_transient_db_error correctly calls
                      -- permanent — and the whole batch of billable usage would
                      -- be dropped over one unattributable row. Degrading that
                      -- row to unattributed keeps the spend.
                      (SELECT i.id FROM interactions i WHERE i.id = :interaction_id),
                      :model
                    )
                    """
                ),
                batch,
            )
            conn.execute(
                text(
                    """
                    INSERT INTO billing_usage_daily (
                      id, service_id, tenant_id, environment, usage_date, units, cost_inr
                    ) VALUES (
                      :id, :service_id, :tenant_id, :environment, :usage_date, :units, :cost_inr
                    )
                    ON CONFLICT (service_id, tenant_id, environment, usage_date) DO UPDATE SET
                      units = billing_usage_daily.units + EXCLUDED.units,
                      cost_inr = billing_usage_daily.cost_inr + EXCLUDED.cost_inr
                    """
                ),
                [
                    {
                        "id": f"bu-{service_id}-{tid}-{env}-{day.isoformat()}",
                        "service_id": service_id,
                        "tenant_id": tid,
                        "environment": env,
                        "usage_date": day.isoformat(),
                        "units": totals["units"],
                        "cost_inr": totals["cost_inr"],
                    }
                    for (service_id, tid, env, day), totals in daily.items()
                ],
            )
    except Exception as exc:
        # Metering must never break product paths, but silently discarding the
        # batch loses billable usage on every transient database blip. Put it
        # back at the front of the buffer (oldest first) and let the next flush
        # retry; the overflow ceiling still bounds a sustained outage.
        #
        # Only transient failures are worth retrying. A deterministic one — a
        # constraint violation, a type error, a schema drift — fails identically
        # forever, so requeueing it turned one bad batch into a permanent loop
        # that also pushed every subsequent event out through the overflow.
        if not _is_transient_db_error(exc):
            logger.exception(
                "usage_meter_flush_failed events=%s (dropped: not retryable)", len(batch)
            )
            return 0
        logger.exception("usage_meter_flush_failed events=%s (requeued)", len(batch))
        with _buffer_lock:
            _buffer[:0] = batch
            overflow = len(_buffer) - _buffer_max_events()
            if overflow > 0:
                del _buffer[:overflow]
                logger.error("usage_meter_buffer_overflow dropped=%s", overflow)
        return 0
    return len(batch)


def _is_transient_db_error(exc: BaseException) -> bool:
    """True for failures a later identical flush could plausibly survive."""
    from sqlalchemy.exc import DBAPIError, OperationalError

    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError):
        return bool(getattr(exc, "connection_invalidated", False))
    return False


def shutdown() -> int:
    """Stop the flusher and drain the buffer once. Idempotent.

    Called from the FastAPI lifespan shutdown and from atexit. Flushing *after*
    the worker has stopped avoids a final flush racing an in-flight one and
    splitting the last batch across two transactions.
    """
    _shutdown.set()
    _flush_now.set()
    worker = _flusher
    if worker is not None and worker.is_alive() and worker is not threading.current_thread():
        worker.join(timeout=5.0)
    return flush()


atexit.register(shutdown)


def record_chat_usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None = None,
    model: str | None = None,
    source_ref: str | None = None,
    interaction_id: str | None = None,
) -> None:
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    estimated_split = False
    if pt <= 0 and ct <= 0 and total_tokens:
        # Fallback split when only total is known. Flagged in meta so a cost
        # audit can tell a measured split from this guess — the two prices
        # differ 8x, so a silent estimate is not a neutral one.
        pt = int(total_tokens * 0.7)
        ct = int(total_tokens) - pt
        estimated_split = True
    total = pt + ct
    if total <= 0:
        return
    cost = chat_cost_inr(prompt_tokens=pt, completion_tokens=ct)
    record_usage(
        service_id=SERVICE_CHAT,
        units=Decimal(total) / Decimal(1000),
        cost_inr=cost,
        meta={
            "promptTokens": pt,
            "completionTokens": ct,
            "model": model,
            "splitEstimated": estimated_split,
        },
        source_ref=source_ref,
        interaction_id=interaction_id,
        model=model,
    )


def record_embed_usage(
    *,
    prompt_tokens: int | None,
    deployment: str | None = None,
    batch_size: int | None = None,
    source_ref: str | None = None,
    interaction_id: str | None = None,
) -> None:
    pt = int(prompt_tokens or 0)
    if pt <= 0:
        return
    record_usage(
        service_id=SERVICE_EMBED,
        units=Decimal(pt) / Decimal(1000),
        cost_inr=embed_cost_inr(prompt_tokens=pt),
        meta={"promptTokens": pt, "deployment": deployment, "batchSize": batch_size},
        source_ref=source_ref,
        interaction_id=interaction_id,
        # The embedding deployment is the billable model dimension.
        model=deployment,
    )


def record_tts_usage(
    *,
    chars: int,
    voice: str | None = None,
    cache_hit: bool = False,
    source_ref: str | None = None,
    interaction_id: str | None = None,
) -> None:
    if cache_hit or chars <= 0:
        return
    record_usage(
        service_id=SERVICE_TTS,
        units=Decimal(int(chars)) / Decimal(1000),
        cost_inr=tts_cost_inr(chars=chars),
        meta={"chars": chars, "voice": voice},
        source_ref=source_ref,
        interaction_id=interaction_id,
        # For TTS the voice *is* the priced dimension (tts_price_tiers keys off
        # it: neural vs HD differ materially), so it is what belongs in the
        # model column.
        model=voice,
    )


def record_stt_usage(
    *,
    audio_bytes: int,
    content_type: str | None = None,
    minutes: float | None = None,
    language: str | None = None,
    source_ref: str | None = None,
    interaction_id: str | None = None,
    model: str | None = None,
) -> None:
    mins = minutes if minutes is not None else estimate_stt_minutes(audio_bytes, content_type)
    if mins <= 0:
        return
    record_usage(
        service_id=SERVICE_STT,
        units=_to_decimal(mins),
        cost_inr=stt_cost_inr(minutes=mins),
        meta={
            "audioBytes": audio_bytes,
            "minutesEstimated": minutes is None,
            "language": language,
            "contentType": content_type,
        },
        source_ref=source_ref,
        interaction_id=interaction_id,
        # Azure STT prices per tier, not per locale, so the recognition language
        # is the closest thing to a billable model dimension when the caller
        # does not name one.
        model=model or language,
    )


def sync_price_book(conn: Any | None = None) -> None:
    """Upsert metered Azure services with current env-derived INR unit costs."""
    book = unit_cost_book_inr()

    def _upsert(c: Any) -> None:
        for sid, row in book.items():
            c.execute(
                text(
                    """
                    INSERT INTO billing_services (
                      id, name, unit, unit_cost_inr, provider, category, color
                    ) VALUES (
                      :id, :name, :unit, :unit_cost_inr, :provider, :category, :color
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      name = EXCLUDED.name,
                      unit = EXCLUDED.unit,
                      unit_cost_inr = EXCLUDED.unit_cost_inr,
                      provider = EXCLUDED.provider,
                      category = EXCLUDED.category,
                      color = EXCLUDED.color,
                      updated_at = now()
                    """
                ),
                {"id": sid, **row},
            )

    if conn is not None:
        _upsert(conn)
        return
    with _engine().begin() as c:
        _upsert(c)
