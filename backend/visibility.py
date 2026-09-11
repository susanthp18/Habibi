"""Which customers an actor may see, within their tenant.

Pass 1 gave every route a permission, which answers *what* an actor may do.
Nothing answered *which records* — so an agent holding ``customers:read``, the
most ordinary grant in the system, could read every customer in the portfolio.
For a collections product that is the whole book: balances, phone numbers,
payment history, call transcripts.

The schema already models ownership and nothing consulted it:
``customers.assigned_user_id`` names the agent, ``users.team_id`` places them,
and ``teams.supervisor_user_id`` names who oversees that team.

Scopes
------
Each scope is a grant (``authz.CUSTOMERS_READ_ALL`` / ``CUSTOMERS_READ_TEAM``),
handed out by ``authz.ROLE_DEFAULTS`` and movable from the Roles screen. It
used to be the role's *name*, which meant a renamed role changed its reach.

``ALL``
    Admins, and the oversight roles — QA reviewers, compliance officers, the
    DPO. Deliberate: a QA reviewer who can only see one agent's calls cannot
    sample across agents, which is the entire job. Scoping them to a book would
    look like tighter security and would break the control it exists to serve.
``TEAM``
    Supervisors: their own assigned customers, plus everyone assigned to a
    member of a team they supervise. Note *supervise*, not *share a team_id
    with* — in this data supervisors sit in their own "supervisors" team and
    oversee others through ``teams.supervisor_user_id``. Reading it the obvious
    way would have shown a supervisor their fellow supervisors' customers and
    hidden their actual reports'.
``OWN``
    Agents, and anyone holding neither grant. Unknown means most restricted,
    not most permissive.

The unassigned pool
-------------------
Every scope except ALL also sees customers with no assignee. That is a business
decision, not a loophole, and it was made against the data: **13 of 20 customers
in the seed have no assignee, and two of the five agents have none at all.**
Hiding unassigned accounts would give those agents an empty screen and make 13
customers unreachable by anyone but an admin — while the unassigned queue is
precisely the pool agents are supposed to work from. Set
``VISIBILITY_UNASSIGNED_POOL=0`` to tighten it where a deployment assigns
everything up front.

Reads only, for now
-------------------
This scopes what an actor can *see*. The by-id write guards in ``db`` stay at
tenant granularity, because narrowing them needs product answers this module
should not invent: whether an agent may claim an unassigned account, whether
``takeover_conversation`` — a handover feature — should refuse a customer
assigned to someone else. Over-tightening a write path breaks a workflow
silently, and guessing at it would be worse than the gap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from env_utils import env_bool

logger = logging.getLogger(__name__)

ALL = "all"
TEAM = "team"
OWN = "own"



@dataclass(frozen=True)
class Visibility:
    """The resolved scope for one actor."""

    user_id: str
    scope: str
    reason: str

    @property
    def is_unrestricted(self) -> bool:
        return self.scope == ALL


def enforcement_enabled() -> bool:
    """True when customer visibility is narrowed by role.

    Follows :func:`authz.enforcement_enabled` rather than introducing a second
    switch: object-level scoping without route-level permissions protects
    nothing, and the two being separately configurable is mostly a way to end up
    with one of them off by accident. ``VISIBILITY_ENFORCE`` overrides.
    """
    import authz

    return env_bool("VISIBILITY_ENFORCE", default=authz.enforcement_enabled())


def unassigned_pool_visible() -> bool:
    return env_bool("VISIBILITY_UNASSIGNED_POOL", default=True)


def resolve(user_id: str | None) -> Visibility:
    """The scope ``user_id`` acts with."""
    uid = (user_id or "").strip()
    if not enforcement_enabled():
        return Visibility(uid, ALL, "enforcement disabled")
    if not uid:
        # No identity and enforcement on: the route layer should already have
        # rejected this, so treat it as the tightest scope rather than assume.
        return Visibility("", OWN, "no actor")

    import authz

    # The reach is a grant, not a role name: ``authz.ROLE_DEFAULTS`` hands the
    # oversight roles ``CUSTOMERS_READ_ALL`` and supervisors
    # ``CUSTOMERS_READ_TEAM``, and the Roles screen can move either. A role
    # that was renamed, or a new one, no longer changes its reach by accident.
    perms = authz.actor_permissions(uid)
    if authz.CUSTOMERS_READ_ALL in perms:
        return Visibility(uid, ALL, authz.CUSTOMERS_READ_ALL)
    if authz.CUSTOMERS_READ_TEAM in perms:
        return Visibility(uid, TEAM, authz.CUSTOMERS_READ_TEAM)
    if not perms:
        return Visibility(uid, OWN, "no permissions resolved")
    return Visibility(uid, OWN, "own book")


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------

#: A **constant** SQL fragment, identical for every caller and every query, with
#: the scope carried entirely in bind parameters.
#:
#: Building this string per-actor would have been the obvious approach and a bad
#: one: a predicate assembled from a role name is a predicate that can be
#: assembled wrongly, and it defeats statement caching besides. Here there is one
#: string to review, no interpolation, and ``vis_all`` collapses the whole thing
#: to a constant true when the actor is unscoped — which is also how the feature
#: switch works, so "disabled" and "admin" take the identical code path.
#:
#: The team subquery is uncorrelated (it depends only on ``:vis_actor``), so
#: Postgres evaluates it once as a hashed subplan rather than per row.
CUSTOMER_PREDICATE = """(
    :vis_all
    OR {alias}.assigned_user_id = :vis_actor
    OR (:vis_pool AND {alias}.assigned_user_id IS NULL)
    OR (:vis_team AND {alias}.assigned_user_id IN (
          SELECT u.id FROM users u
            JOIN teams t ON t.id = u.team_id
           WHERE t.supervisor_user_id = :vis_actor))
)"""


def predicate(alias: str = "c") -> str:
    """The SQL fragment, bound to a customers alias already in the query."""
    if not alias.isidentifier():
        raise ValueError(f"visibility.predicate: {alias!r} is not a valid alias")
    return CUSTOMER_PREDICATE.format(alias=alias)


def params(user_id: str | None = None) -> dict[str, Any]:
    """Bind parameters for :data:`CUSTOMER_PREDICATE`.

    Resolves the actor from the request context when not given one, so callers
    in ``db`` do not each have to remember to thread it through.
    """
    if user_id is None:
        import actor_context

        user_id = actor_context.get_actor_user_id()
    vis = resolve(user_id)
    return {
        "vis_all": vis.is_unrestricted,
        "vis_team": vis.scope == TEAM,
        "vis_pool": vis.scope != ALL and unassigned_pool_visible(),
        "vis_actor": vis.user_id,
    }
