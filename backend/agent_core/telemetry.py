"""Optional OpenTelemetry spans. Content capture stays off.

If ``opentelemetry-api`` is not installed the tracer is a no-op — Postgres
remains the audit. This module must never sit on the voice audio path with
exporter I/O; callers record spans around analysis-profile work.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

try:
    from opentelemetry import trace as _otel_trace

    _TRACER = _otel_trace.get_tracer("bigbound.agent")
except Exception:  # pragma: no cover - optional dependency
    _TRACER = None


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[None]:
    if _TRACER is None:
        yield
        return
    with _TRACER.start_as_current_span(name) as sp:
        for key, value in attrs.items():
            if value is None:
                continue
            # Never put transcript / tool args on the span.
            if key in {"content", "input", "output", "transcript", "arguments"}:
                continue
            try:
                sp.set_attribute(key, value)
            except Exception:
                pass
        yield
