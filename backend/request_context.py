"""Request-scoped correlation ids for logging.

``RequestIdMiddleware`` already assigned an ``X-Request-Id`` and put it on
``request.state``, which means only code holding the ``Request`` object could
see it — that is, almost nothing. Every log line written from ``db``,
``voice`` or a worker thread was therefore unattributable, which is the reason
the audit called the system operationally blind even where it *did* log.

This mirrors :mod:`actor_context`: a ``ContextVar`` set by the middleware and
read by the log formatter. It is deliberately a separate module from
``actor_context`` because that one is an authorization input — a bug that let a
log id leak into identity resolution would be a security bug, and the way to
make that impossible is to not put them in the same place.

Context propagation note: ``BaseHTTPMiddleware`` runs the downstream app in a
task spawned from the middleware's context, and anyio copies the context at
spawn time — so a value set *before* ``call_next`` is visible to the endpoint.
That is the same mechanism ``actor_context`` already relies on.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_actor: ContextVar[str | None] = ContextVar("log_actor", default=None)


def set_request_id(value: str | None) -> Any:
    """Set the id; returns a token for :func:`reset_request_id`."""
    return _request_id.set((value or "").strip() or None)


def reset_request_id(token: Any) -> None:
    _request_id.reset(token)


def get_request_id() -> str | None:
    return _request_id.get()


def set_actor(value: str | None) -> Any:
    return _actor.set((value or "").strip() or None)


def reset_actor(token: Any) -> None:
    _actor.reset(token)


def get_actor() -> str | None:
    return _actor.get()
