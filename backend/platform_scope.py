"""Writing a tenant-less row -- the one sanctioned way.

Row security (``rls.py``) lets every tenant *read* a row whose ``tenant_id`` is
NULL -- the statutory rule sets, the platform budget -- and lets no tenant
*write* one, so a tenant cannot publish law for every other tenant. The write
side admits such a row only while ``app.platform_scope`` is ``global`` in the
current transaction, and only this module sets it, after checking the actor
holds :data:`authz.PLATFORM_WRITE`.

It used to be "the owner's job, by migration or seed" with nothing in the app
able to do it, while the Compliance screen offered Submit and Approve on the
statutory sets: every click was a Postgres row-security violation and a 500.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

GUC = "app.platform_scope"
VALUE = "global"


def enter(conn: Any, *, actor_user_id: str | None, reason: str) -> None:
    """Open global rows to writes for the rest of this transaction.

    ``set_config(..., true)`` is transaction-local: it ends with the commit or
    rollback, so a pooled connection cannot carry the scope into the next
    request.
    """
    import authz

    if not actor_user_id or not authz.has_permission(actor_user_id, authz.PLATFORM_WRITE):
        logger.warning(
            "platform scope refused · actor=%s · %s · lacks %s",
            actor_user_id,
            reason,
            authz.PLATFORM_WRITE,
        )
        raise PermissionError("platform_write_required")
    conn.execute(text("SELECT set_config(:guc, :value, true)"), {"guc": GUC, "value": VALUE})
    logger.info("platform scope · actor=%s · %s", actor_user_id, reason)


def enter_unattended(conn: Any, *, reason: str) -> None:
    """Platform scope for a bootstrap with no signed-in actor -- the seeders.

    ``scripts/seed_policy_rules.py`` drafts the statutory sets on a fresh
    install, through the application role, under row security; with no actor
    there is no permission to check. It is named apart from :func:`enter` so
    ``tests/test_platform_scope.py`` can hold every caller to the bootstrap
    paths, and it logs at WARNING so an unexpected caller is visible.
    """
    conn.execute(text("SELECT set_config(:guc, :value, true)"), {"guc": GUC, "value": VALUE})
    logger.warning("platform scope (unattended) · %s", reason)
