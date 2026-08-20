"""Metrics exposition and structured logging.

Two properties are load-bearing here. Metric labels must come from a bounded
set — a series per customer id takes the scrape down on a busy day — and
instrumentation must never be the reason a request fails.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

import observability


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------


def test_render_returns_prometheus_text() -> None:
    body, content_type = observability.render()
    assert b"http_requests_total" in body
    assert "text/plain" in content_type


def test_scrape_time_collectors_are_present() -> None:
    body, _ = observability.render()
    text = body.decode()
    # Read from the existing snapshot sources rather than duplicated state.
    assert "db_pool_capacity" in text
    assert "voice_calls_max_concurrent" in text


def test_breaker_metrics_are_actually_emitted() -> None:
    """Regression: ``circuit_breaker.snapshots()`` returns a LIST of dicts, each
    carrying its own ``name`` — not a mapping keyed by name. Reading it as a
    mapping emitted nothing at all, which is the worst possible failure for a
    signal whose whole job is to say a dependency is down."""
    import circuit_breaker

    circuit_breaker.get_breaker("obs-test-breaker")
    samples = list(observability._breaker_samples())
    assert samples, "no breaker samples emitted despite a registered breaker"

    names = {labels["breaker"] for _m, labels, _v in samples}
    assert "obs-test-breaker" in names

    # A closed breaker reports exactly one state series set to 1.
    states = {
        labels["state"]: value
        for metric, labels, value in samples
        if metric == "circuit_breaker_state" and labels["breaker"] == "obs-test-breaker"
    }
    assert states.get("closed") == 1.0
    assert states.get("open") == 0.0


def test_job_queue_metrics_cover_every_queue_and_status() -> None:
    """Dead-letter jobs stop silently today; this is the series that alerts.

    A missing series and a zero look identical in a graph and behave very
    differently in an alert rule, so every (queue, status) pair must be emitted
    even when the count is zero.
    """
    samples = list(observability._job_queue_samples())
    depth = {
        (labels["queue"], labels["status"])
        for metric, labels, _v in samples
        if metric == "job_queue_depth"
    }
    for queue in observability._JOB_QUEUES:
        for status in ("queued", "running", "failed", "dead"):
            assert (queue, status) in depth, f"missing {queue}/{status}"


def test_job_queue_backlog_age_is_emitted_per_queue() -> None:
    """Depth alone does not distinguish a fast queue of 500 from a stuck 3."""
    ages = {
        labels["queue"]
        for metric, labels, _v in observability._job_queue_samples()
        if metric == "job_queue_oldest_seconds"
    }
    assert ages == set(observability._JOB_QUEUES)


def test_rate_limit_throttles_are_exported() -> None:
    """kb_rate_limit.throttle_metrics() said 'surfaced by /metrics' before any
    /metrics existed. It does now."""
    import kb_rate_limit

    kb_rate_limit._record_throttle("retrieve:test-tenant")
    samples = list(observability._rate_limit_samples())
    keys = {labels["key"] for _m, labels, _v in samples}
    assert "retrieve:test-tenant" in keys


def test_error_tracking_is_a_noop_without_a_dsn(monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    observability.setup_error_tracking()  # must not raise


def test_error_tracking_survives_a_bad_dsn(monkeypatch) -> None:
    """A broken error tracker must never stop the process from booting."""
    monkeypatch.setenv("SENTRY_DSN", "not-a-valid-dsn")
    observability.setup_error_tracking()  # must not raise


def test_sentry_scrub_redacts_pii_from_exception_values() -> None:
    """send_default_pii=False does not touch text we put in the message."""
    event = {
        "logentry": {"message": "caller read 4111 1111 1111 1111"},
        "exception": {"values": [{"value": "failed for +91 98765 43210"}]},
    }
    scrubbed = observability._scrub_event(event, None)
    assert "4111 1111 1111 1111" not in scrubbed["logentry"]["message"]
    assert "98765 43210" not in scrubbed["exception"]["values"][0]["value"]


def test_sentry_scrub_tolerates_a_malformed_event() -> None:
    assert observability._scrub_event({}, None) == {}
    assert observability._scrub_event({"exception": {"values": [{}]}}, None) is not None


def test_register_collectors_is_idempotent() -> None:
    """Re-registering a name on a prometheus registry raises — so this must not."""
    observability.register_collectors()
    observability.register_collectors()
    observability.render()


def test_a_broken_collector_does_not_break_the_scrape(monkeypatch) -> None:
    def _explode():
        raise RuntimeError("pool is gone")

    monkeypatch.setattr(observability, "_pool_samples", _explode)
    collector = observability._SnapshotCollector("t", "d", observability._pool_samples)
    assert list(collector.collect()) == []


# ---------------------------------------------------------------------------
# Cardinality — the rule that keeps a metrics backend alive
# ---------------------------------------------------------------------------


def test_request_metric_labels_are_bounded() -> None:
    """Route templates, not raw paths."""
    observability.observe_request(
        method="GET", route="/customers/{customer_id}", status_code=200, seconds=0.01
    )
    text = observability.render()[0].decode()
    assert 'route="/customers/{customer_id}"' in text


def test_status_is_bucketed_into_classes_not_codes() -> None:
    observability.observe_request(method="GET", route="/x", status_code=404, seconds=0.01)
    observability.observe_request(method="GET", route="/x", status_code=451, seconds=0.01)
    text = observability.render()[0].decode()
    assert 'status="4xx"' in text
    assert 'status="404"' not in text


def test_no_metric_is_labelled_by_an_unbounded_identifier() -> None:
    """A label named for a customer/actor/tenant is an outage waiting to happen."""
    text = observability.render()[0].decode()
    for forbidden in ("customer_id=", "actor=", "tenant_id=", "interaction_id="):
        assert forbidden not in text, f"unbounded label in metrics: {forbidden}"


# ---------------------------------------------------------------------------
# End to end through the app
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "obs-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def _hdr(actor: str = "priya-nair") -> dict[str, str]:
    return {"X-API-Key": "obs-test-key", "X-Actor-User-Id": actor}


def test_metrics_endpoint_requires_permission(client: TestClient) -> None:
    """Pool occupancy and call volume are not public."""
    assert client.get("/metrics", headers=_hdr("arjun-mehta")).status_code == 403


def test_metrics_endpoint_serves_admin(client: TestClient) -> None:
    res = client.get("/metrics", headers=_hdr("priya-nair"))
    assert res.status_code == 200
    assert "http_requests_total" in res.text


def test_metrics_endpoint_is_not_public(client: TestClient) -> None:
    assert client.get("/metrics").status_code == 401


def test_requests_are_counted(client: TestClient) -> None:
    client.get("/health")
    text = client.get("/metrics", headers=_hdr()).text
    assert 'route="/health"' in text


def test_auth_failures_are_counted(client: TestClient) -> None:
    """Metrics sit outside the auth gate, so a 401 spike is visible."""
    client.get("/staff")  # no key -> 401
    text = client.get("/metrics", headers=_hdr()).text
    assert 'status="4xx"' in text


def test_authz_denials_are_counted(client: TestClient) -> None:
    client.get("/webhook-endpoints", headers=_hdr("arjun-mehta"))
    text = client.get("/metrics", headers=_hdr()).text
    assert "authz_denials_total" in text
    assert "perm-integrations-read" in text


def test_request_id_is_echoed_and_bound(client: TestClient) -> None:
    res = client.get("/health", headers={"X-Request-Id": "abc-123"})
    assert res.headers["X-Request-Id"] == "abc-123"


def test_unmatched_route_does_not_create_a_label_per_path(client: TestClient) -> None:
    client.get("/no/such/route/aaa", headers=_hdr())
    client.get("/no/such/route/bbb", headers=_hdr())
    text = client.get("/metrics", headers=_hdr()).text
    assert "<unmatched>" in text
    assert "/no/such/route/aaa" not in text


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def test_json_formatter_emits_one_object_per_line() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    payload = json.loads(observability.JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t"
    assert payload["ts"].endswith("Z")


def test_json_formatter_redacts_pii() -> None:
    """Log aggregation is exactly where a spoken card number gets retained."""
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "caller gave 4111 1111 1111 1111", (), None
    )
    payload = json.loads(observability.JsonFormatter().format(record))
    assert "4111 1111 1111 1111" not in payload["message"]
    assert "1111" in payload["message"]  # masked tail retained


def test_json_formatter_survives_unserialisable_extra() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", (), None)
    record.thing = object()  # type: ignore[attr-defined]
    payload = json.loads(observability.JsonFormatter().format(record))
    assert "thing" in payload


def test_json_formatter_includes_exception_text() -> None:
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    payload = json.loads(observability.JsonFormatter().format(record))
    assert "kaboom" in payload["exception"]


def test_json_formatter_carries_request_context() -> None:
    import request_context

    token = request_context.set_request_id("req-42")
    actor_token = request_context.set_actor("priya-nair")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "x", (), None)
        payload = json.loads(observability.JsonFormatter().format(record))
        assert payload["requestId"] == "req-42"
        assert payload["actor"] == "priya-nair"
    finally:
        request_context.reset_actor(actor_token)
        request_context.reset_request_id(token)


def test_json_logging_is_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert observability.json_logs_enabled() is False


def test_setup_logging_replaces_handlers_rather_than_adding(monkeypatch) -> None:
    """Adding a handler here is how every line ends up logged twice."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    root = logging.getLogger()
    before = len(root.handlers)
    observability.setup_logging()
    try:
        assert len(root.handlers) <= max(before, 1)
    finally:
        for handler in root.handlers:
            handler.setFormatter(logging.Formatter())
