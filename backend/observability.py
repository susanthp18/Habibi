"""Metrics and structured logging.

The audit's finding was that the system is operationally blind: no metrics, no
traces, no structured logs, no error tracking. Log lines were f-strings through
stdlib ``logging``, so when a call went wrong there was no p95 to alert on and
no way to answer "is it Azure, the DB, or us?".

This module closes the metrics and logging halves. Traces are deliberately not
attempted here — OTLP spans are useful only once a collector exists, whereas a
Prometheus text endpoint is useful with ``curl`` on day one.

What is instrumented, and why these
-----------------------------------
Every signal here is one somebody would actually page on, or one the audit
showed was being computed and then thrown away:

* **HTTP** — rate, latency histogram, status class. Labelled by *route
  template*, never the raw path: ``/customers/{customer_id}`` is one series,
  while the raw path would mint one per customer and take the scrape down.
* **Authorization denials** — the pass-1 authz layer logs a warning per denial
  and counts nothing. A spike is either a misconfigured role or someone probing.
* **Voice admission** — the pass-1 cap already tracks admitted/rejected/high
  water in memory, reachable only by reading ``/voice/status`` by hand.
* **Database pool** — ``db.pool_snapshot()`` existed purely so ``/ready`` could
  fail on exhaustion. Pool saturation is the failure mode behind the sync-handler
  problem in the audit, and nothing could see it coming.
* **Circuit breakers** — ``circuit_breaker.snapshots()`` likewise.

The last three are read at *scrape* time rather than pushed, so they cost
nothing between scrapes and cannot drift from the values ``/ready`` reports.

Cardinality
-----------
Every label value here is drawn from a bounded set (route templates, HTTP
methods, status classes, permission ids, breaker names). Nothing is labelled by
customer, interaction, tenant or actor. That is a hard rule: a metric labelled
by a user id is an outage waiting for a busy day.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Iterable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)

#: A private registry rather than the process-global default. The default one
#: is implicitly shared with any library that decides to register something, and
#: it makes tests order-dependent — re-registering a name on it raises.
REGISTRY = CollectorRegistry()


# ---------------------------------------------------------------------------
# Request metrics
# ---------------------------------------------------------------------------

#: Buckets chosen for this workload, not the library default. The interesting
#: region for a CRM read is 10ms-1s; above 5s the statement timeout (15s on the
#: API role) is the real story and finer resolution buys nothing.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

http_requests = Counter(
    "http_requests_total",
    "HTTP requests by route template, method and status class.",
    ["method", "route", "status"],
    registry=REGISTRY,
)

http_latency = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by route template.",
    ["method", "route"],
    buckets=_LATENCY_BUCKETS,
    registry=REGISTRY,
)

http_in_flight = Gauge(
    "http_requests_in_flight",
    "HTTP requests currently being served.",
    registry=REGISTRY,
)

authz_denials = Counter(
    "authz_denials_total",
    "Requests refused by the route permission registry.",
    ["route", "permission"],
    registry=REGISTRY,
)

voice_calls_admitted = Counter(
    "voice_calls_admitted_total",
    "Voice calls granted a concurrency slot.",
    registry=REGISTRY,
)

voice_calls_rejected = Counter(
    "voice_calls_rejected_total",
    "Voice calls refused because the process was at capacity.",
    registry=REGISTRY,
)


def observe_request(*, method: str, route: str, status_code: int, seconds: float) -> None:
    """Record one finished request. Never raises — see :func:`_safe`."""
    status_class = f"{status_code // 100}xx"
    http_requests.labels(method=method, route=route, status=status_class).inc()
    http_latency.labels(method=method, route=route).observe(seconds)


def observe_authz_denial(*, route: str, permission: str) -> None:
    authz_denials.labels(route=route, permission=permission).inc()


# ---------------------------------------------------------------------------
# Scrape-time collectors — read existing snapshots rather than duplicating state
# ---------------------------------------------------------------------------


class _SnapshotCollector(Collector):
    """Expose an existing ``snapshot()``-style dict as gauges at scrape time.

    Pull rather than push, for two reasons: these values already have a single
    authoritative source (``db.pool_snapshot``, ``circuit_breaker.snapshots``,
    ``voice.admission.snapshot``), and mirroring them into pushed gauges would
    let the metric and ``/ready`` disagree about the same number.
    """

    def __init__(self, name: str, doc: str, source: Callable[[], Iterable[tuple[str, dict[str, Any], float]]]):
        self._name = name
        self._doc = doc
        self._source = source

    def collect(self):  # noqa: D102 - prometheus_client protocol
        try:
            samples = list(self._source())
        except Exception:
            # A broken collector must not take the whole scrape down, and must
            # not be silent about it either.
            logger.exception("metrics collector %s failed", self._name)
            return
        seen: dict[str, GaugeMetricFamily] = {}
        for metric_name, labels, value in samples:
            family = seen.get(metric_name)
            if family is None:
                family = GaugeMetricFamily(metric_name, self._doc, labels=list(labels))
                seen[metric_name] = family
            family.add_metric([str(v) for v in labels.values()], value)
        yield from seen.values()


def _pool_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    import db

    snap = db.pool_snapshot()
    yield ("db_pool_checked_out", {}, float(snap.get("checkedOut") or 0))
    yield ("db_pool_available", {}, float(snap.get("available") or 0))
    yield ("db_pool_capacity", {}, float(snap.get("capacity") or 0))


def _breaker_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    import circuit_breaker

    # snapshots() returns a LIST of per-breaker dicts, each carrying its own
    # "name" — not a mapping keyed by name. Reading it as a mapping silently
    # produced no breaker metrics at all, which is the worst possible failure
    # for a signal whose entire job is to tell you a dependency is down.
    for snap in circuit_breaker.snapshots() or []:
        if not isinstance(snap, dict):
            continue
        name = str(snap.get("name") or "unknown")
        state = str(snap.get("state") or "unknown")
        # One series per (breaker, state) with a 0/1 value is what lets a query
        # say "which breakers are open" without string comparison in PromQL.
        for candidate in ("closed", "open", "half_open"):
            yield ("circuit_breaker_state", {"breaker": name, "state": candidate}, 1.0 if state == candidate else 0.0)
        failures = snap.get("failures")
        if isinstance(failures, (int, float)):
            yield ("circuit_breaker_failures", {"breaker": name}, float(failures))


def _voice_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    from voice import admission

    snap = admission.snapshot()
    yield ("voice_calls_active", {}, float(snap.get("activeCalls") or 0))
    yield ("voice_calls_max_concurrent", {}, float(snap.get("maxConcurrentCalls") or 0))
    yield ("voice_calls_high_water_mark", {}, float(snap.get("highWaterMark") or 0))


#: The three SKIP LOCKED queues, all sharing the same status vocabulary
#: (queued / running / succeeded / failed / dead). ``dead`` is the dead-letter
#: state — jobs that exhausted their attempts and that nothing surfaces today.
_JOB_QUEUES = ("bot_turn_jobs", "whatsapp_outbound_jobs", "kb_index_jobs")

_JOB_DEPTH_SQL = " UNION ALL ".join(
    f"""
    SELECT '{table}' AS queue, status,
           count(*) AS n,
           COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0) AS oldest_s
      FROM {table}
     GROUP BY status
    """
    for table in _JOB_QUEUES
)


def _job_queue_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    """Queue depth, dead-letter size and backlog age.

    The audit's finding was that a job exhausting its attempts stops silently:
    nothing surfaces it, nothing alerts, and the first anyone hears is a
    customer asking why they never got a reply. ``job_queue_depth{status="dead"}``
    is that alert.

    ``job_queue_oldest_seconds`` matters more than depth for paging: a queue of
    500 draining fast is healthy, a queue of 3 stuck for an hour is not.

    This is the only collector that touches the database. It is one grouped
    index scan per queue, and a failure degrades to "no job metrics" rather
    than taking the whole scrape down (see _SnapshotCollector.collect).
    """
    from sqlalchemy import text

    import db

    with db.engine.connect() as conn:
        rows = conn.execute(text(_JOB_DEPTH_SQL)).mappings().all()

    # Emit an explicit zero for every (queue, status) pair, so a queue that has
    # never had a dead job still produces the series an alert rule reads. A
    # missing series and a zero look identical in a graph and behave very
    # differently in an alert.
    seen: set[tuple[str, str]] = set()
    for row in rows:
        queue, status = str(row["queue"]), str(row["status"])
        seen.add((queue, status))
        yield ("job_queue_depth", {"queue": queue, "status": status}, float(row["n"]))
        if status == "queued":
            yield ("job_queue_oldest_seconds", {"queue": queue}, float(row["oldest_s"] or 0))

    for queue in _JOB_QUEUES:
        for status in ("queued", "running", "failed", "dead"):
            if (queue, status) not in seen:
                yield ("job_queue_depth", {"queue": queue, "status": status}, 0.0)
        if (queue, "queued") not in seen:
            yield ("job_queue_oldest_seconds", {"queue": queue}, 0.0)


def _rate_limit_samples() -> Iterable[tuple[str, dict[str, Any], float]]:
    """KB rate-limit throttles.

    ``kb_rate_limit.throttle_metrics()`` already existed, and its docstring
    already said "surfaced by /metrics" — for an endpoint that did not exist.
    The key is ``bucket:tenant``, which is a bounded label set.
    """
    import kb_rate_limit

    for key, count in (kb_rate_limit.throttle_metrics() or {}).items():
        yield ("rate_limit_throttled", {"key": str(key)}, float(count))


_COLLECTORS_REGISTERED = False


def register_collectors() -> None:
    """Attach the scrape-time collectors. Idempotent."""
    global _COLLECTORS_REGISTERED
    if _COLLECTORS_REGISTERED:
        return
    REGISTRY.register(_SnapshotCollector("db_pool", "SQLAlchemy connection pool occupancy.", _pool_samples))
    REGISTRY.register(_SnapshotCollector("circuit_breakers", "Circuit breaker state and failure counts.", _breaker_samples))
    REGISTRY.register(_SnapshotCollector("voice_admission", "Voice concurrency admission control.", _voice_samples))
    REGISTRY.register(_SnapshotCollector("job_queues", "SKIP LOCKED job queue depth, dead letters and backlog age.", _job_queue_samples))
    REGISTRY.register(_SnapshotCollector("rate_limits", "Rate-limit throttles since process start.", _rate_limit_samples))
    _COLLECTORS_REGISTERED = True


def render() -> tuple[bytes, str]:
    """``(body, content_type)`` for the ``/metrics`` response."""
    register_collectors()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the request id and actor folded in.

    Two things this does that a plain ``json.dumps(record.__dict__)`` does not:

    * it runs the message through :func:`pii_redact.redact_text`, because log
      aggregation is exactly the kind of place a card number spoken into a
      transcript ends up and is retained indefinitely;
    * it never lets a non-serialisable ``extra`` take the log line down — a
      formatter that raises loses the message it was trying to record.
    """

    _RESERVED = frozenset(
        vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
    ) | {"asctime", "message", "taskName"}

    def __init__(self, *, redact: bool = True) -> None:
        super().__init__()
        self._redact = redact

    def format(self, record: logging.LogRecord) -> str:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        if self._redact:
            try:
                import pii_redact

                message = pii_redact.redact_text(message)
            except Exception:
                pass

        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        }

        request_id = getattr(record, "request_id", None) or _current_request_id()
        if request_id:
            payload["requestId"] = request_id
        actor = getattr(record, "actor", None) or _current_actor()
        if actor:
            payload["actor"] = actor

        for key, value in record.__dict__.items():
            if key in self._RESERVED or key in payload:
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        try:
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            # Last resort: never lose the line.
            return json.dumps({"level": record.levelname, "message": message})


def _current_request_id() -> str | None:
    try:
        import request_context

        return request_context.get_request_id()
    except Exception:
        return None


def _current_actor() -> str | None:
    try:
        import request_context

        return request_context.get_actor()
    except Exception:
        return None


def json_logs_enabled() -> bool:
    """``LOG_FORMAT=json`` turns on structured output.

    Off by default: a developer reading a terminal wants the plain formatter,
    and switching that out from under them is not an improvement.
    """
    return (os.getenv("LOG_FORMAT") or "").strip().lower() == "json"


def setup_error_tracking() -> None:
    """Initialise Sentry when ``SENTRY_DSN`` is set. No-op otherwise.

    Exceptions were logged and lost: a stack trace went to stdout and, with no
    aggregation configured, nowhere else. This is opt-in by DSN rather than by a
    separate flag, so an environment either has somewhere to send errors or it
    does not.

    ``send_default_pii=False`` is not the default in every SDK version and is
    load-bearing here — this process handles collections transcripts, and the
    request bodies Sentry would otherwise attach contain customer PII.
    """
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=(os.getenv("APP_ENV") or "dev").strip().lower(),
            release=(os.getenv("APP_RELEASE") or "").strip() or None,
            # Errors always; traces are sampled and default to off because the
            # tracing story here is Phase 1's remaining item, not this one.
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE") or 0.0),
            send_default_pii=False,
            before_send=_scrub_event,
        )
        logger.info("Sentry error tracking enabled")
    except Exception:
        # A broken error tracker must never stop the process from booting.
        logger.warning("Sentry init failed — continuing without error tracking", exc_info=True)


def _scrub_event(event: dict[str, Any], _hint: Any) -> dict[str, Any]:
    """Redact PII from the message and exception values before they leave.

    ``send_default_pii=False`` stops Sentry attaching request bodies and user
    data; it does not touch text we put in the message ourselves, and on a
    collections line an exception string routinely carries a phone number or a
    card number the caller read aloud.
    """
    try:
        import pii_redact

        message = (event.get("logentry") or {}).get("message")
        if isinstance(message, str):
            event["logentry"]["message"] = pii_redact.redact_text(message)
        for exc in (event.get("exception") or {}).get("values") or []:
            if isinstance(exc.get("value"), str):
                exc["value"] = pii_redact.redact_text(exc["value"])
    except Exception:
        logger.debug("sentry scrub failed", exc_info=True)
    return event


def setup_logging() -> None:
    """Install the JSON formatter on the root handlers when asked for.

    Reconfigures the *existing* handlers rather than adding one, so uvicorn's
    own handlers are converted instead of duplicated — adding a handler here is
    how every line ends up logged twice.
    """
    if not json_logs_enabled():
        return
    formatter = JsonFormatter()
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(formatter)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        for handler in logging.getLogger(name).handlers:
            handler.setFormatter(formatter)
