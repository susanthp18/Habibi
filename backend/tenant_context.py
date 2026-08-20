"""Request-scoped tenant.

``db.TENANT_ID`` is a process-wide constant read from the environment at import
time, and every tenant predicate in ``db.py`` interpolates it. That is correct
for the way this is deployed today — one process serves one tenant — but it
gives the database no way to know which tenant a connection is acting for, so
there is nothing for a row-level-security policy to compare against.

This module is the seam. It holds the active tenant in a ContextVar, defaulting
to the process tenant so that behaviour today is unchanged, and ``db`` publishes
that value to Postgres as the ``app.tenant_id`` GUC on every connection. Once a
request can carry its own tenant (JWT claim, host header), binding it here is
the only change needed on the Python side — the policies already read the GUC.

Deliberately separate from :mod:`actor_context` for the same reason that module
is separate from request ids: identity, audit attribution and tenancy are three
different questions, and a bug in one must not be able to answer another.

The default is read through ``db.TENANT_ID`` rather than from the environment
directly. Two independent reads of ``os.getenv("TENANT_ID")`` would be a second
source of truth, and under RLS a divergence between them is not a visible error
— the SQL predicate would say one tenant, the policy the other, and every query
would quietly return zero rows.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

logger = logging.getLogger(__name__)

#: The GUC that row-level-security policies compare against.
GUC = "app.tenant_id"

#: Tenant ids reach Postgres inside a libpq ``options`` connection string, where
#: whitespace separates arguments and backslash escapes. Rather than escape, we
#: refuse: a tenant id is an internal slug, and one that needs escaping is a
#: configuration mistake worth failing loudly on.
_TENANT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_tenant_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)


class InvalidTenantId(ValueError):
    """A tenant id that cannot be safely carried to Postgres."""


def validate(tenant_id: str) -> str:
    """Return ``tenant_id`` if it is a safe slug, else raise."""
    value = (tenant_id or "").strip()
    if not _TENANT_RE.match(value):
        raise InvalidTenantId(
            f"tenant id {tenant_id!r} must match {_TENANT_RE.pattern} — "
            "it is embedded in the libpq options string and used as a "
            "row-level-security key"
        )
    return value


def default_tenant() -> str:
    """The process tenant — ``db.TENANT_ID``.

    Imported lazily: ``db`` imports this module to install the connection hook,
    so a module-level import here would be circular.
    """
    import db

    return db.TENANT_ID


def current_tenant() -> str:
    """Tenant for the current context, or the process default outside one."""
    return _tenant_var.get() or default_tenant()


def set_tenant(tenant_id: str | None) -> Any:
    """Bind the tenant for this context. Returns a token for :func:`reset`."""
    if tenant_id is None:
        return _tenant_var.set(None)
    return _tenant_var.set(validate(tenant_id))


def reset(token: Any) -> None:
    _tenant_var.reset(token)


@contextmanager
def bind(tenant_id: str | None) -> Iterator[str]:
    """Scope a block of work to one tenant.

    Both halves move together — the Python predicates in ``db`` and the
    ``app.tenant_id`` GUC that policies read — because the connection hook
    resolves the GUC from this same ContextVar at transaction start.
    """
    token = set_tenant(tenant_id)
    try:
        yield current_tenant()
    finally:
        reset(token)


def is_bound() -> bool:
    """True when something explicitly bound a tenant for this context."""
    return _tenant_var.get() is not None
