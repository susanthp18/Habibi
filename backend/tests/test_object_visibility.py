"""Which customers an actor may see, not just which routes they may call.

Pass 1 gave every route a permission. That answers *what* an actor may do and
says nothing about *which records* — so an agent holding ``customers:read``, the
most ordinary grant in the system, could read the entire portfolio: balances,
phone numbers, payment history, transcripts.

These tests hold the two halves that make narrowing safe. The obvious half is
that an agent cannot see another agent's customers. The half that actually
breaks products is the other one: **the unassigned pool stays visible**. 13 of
the 20 customers in the seed have no assignee and two of the five agents have
none at all, so a scope of "strictly your own" would give those agents an empty
screen and strand 13 customers where only an admin could reach them.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import actor_context
import authz
import db
import visibility

#: Agents in `card-collections`. `sara-khan` has assigned customers in the seed;
#: `arjun-mehta` has none, which makes it the actor that would see an empty
#: screen if the unassigned pool were hidden.
AGENT = "sara-khan"
OTHER_AGENT = "arjun-mehta"
#: Supervises the `supervisors` team, whose members include `priya-nair`.
#: Deliberately *not* the supervisor of card-collections — see
#: `test_supervisor_does_not_see_a_team_they_do_not_supervise`.
SUPERVISOR = "david-chen"
ADMIN = "priya-nair"


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    """Scoping follows authz enforcement, which is off in a bare dev tree."""
    monkeypatch.setenv("VISIBILITY_ENFORCE", "1")
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


@pytest.fixture
def as_actor():
    """Run a call as somebody, restoring the previous actor afterwards."""
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user_id,expected",
    [
        (ADMIN, visibility.ALL),
        (SUPERVISOR, visibility.TEAM),
        (AGENT, visibility.OWN),
        (OTHER_AGENT, visibility.OWN),
    ],
)
def test_role_resolves_to_scope(db_tx, user_id: str, expected: str) -> None:
    assert visibility.resolve(user_id).scope == expected


def test_a_user_with_no_roles_gets_the_tightest_scope(db_tx) -> None:
    """Unknown means most restricted. The opposite default is how an
    unclassified role quietly becomes an administrator."""
    assert visibility.resolve("anita-rao").scope == visibility.OWN
    assert visibility.resolve("nobody-at-all").scope == visibility.OWN


def test_oversight_roles_are_deliberately_unscoped(db_tx) -> None:
    """A QA reviewer restricted to one agent's calls cannot sample across
    agents, which is the whole job. Narrowing them would look like tighter
    security while breaking the control it exists to serve."""
    assert visibility._UNSCOPED_ROLES >= {"qa_reviewer", "compliance_officer", "dpo"}


def test_disabled_enforcement_is_the_same_path_as_admin(monkeypatch) -> None:
    monkeypatch.setenv("VISIBILITY_ENFORCE", "0")
    resolved = visibility.resolve(AGENT)
    assert resolved.scope == visibility.ALL
    assert visibility.params(AGENT)["vis_all"] is True


def test_predicate_rejects_an_alias_that_is_not_an_identifier() -> None:
    """The alias is the one part of the predicate that is interpolated."""
    with pytest.raises(ValueError):
        visibility.predicate("c; DROP TABLE customers --")


# ---------------------------------------------------------------------------
# What each actor sees
# ---------------------------------------------------------------------------


def _customer_ids(**kwargs) -> set[str]:
    return {row["id"] for row in db.list_customers(**kwargs)}


def _assigned_to(conn, user_id: str) -> str:
    row = conn.execute(
        text("SELECT id FROM customers WHERE assigned_user_id = :u LIMIT 1"),
        {"u": user_id},
    ).scalar()
    if row is None:
        pytest.skip(f"seed has no customer assigned to {user_id}")
    return row


def _unassigned(conn) -> str:
    row = conn.execute(
        text("SELECT id FROM customers WHERE assigned_user_id IS NULL LIMIT 1")
    ).scalar()
    if row is None:
        pytest.skip("seed has no unassigned customer")
    return row


def test_agent_cannot_see_another_agents_customer(db_tx, as_actor) -> None:
    theirs = _assigned_to(db_tx, AGENT)
    as_actor(OTHER_AGENT)
    assert theirs not in _customer_ids()
    assert db.get_customer(theirs) is None, (
        "the single-customer lookup must narrow too — it shares "
        "_base_customer_row with the list precisely so it cannot drift"
    )


def test_agent_sees_their_own_customer(db_tx, as_actor) -> None:
    theirs = _assigned_to(db_tx, AGENT)
    as_actor(AGENT)
    assert theirs in _customer_ids()
    assert db.get_customer(theirs) is not None


def test_agent_sees_the_unassigned_pool(db_tx, as_actor) -> None:
    """The half that keeps the product working. An agent with no assigned
    customers must still have a queue to work from."""
    pool = _unassigned(db_tx)
    as_actor(OTHER_AGENT)
    assert pool in _customer_ids()
    assert _customer_ids(), "an agent with no assignments would see an empty screen"


def test_the_pool_can_be_closed_for_deployments_that_assign_everything(
    db_tx, as_actor, monkeypatch
) -> None:
    pool = _unassigned(db_tx)
    monkeypatch.setenv("VISIBILITY_UNASSIGNED_POOL", "0")
    as_actor(OTHER_AGENT)
    assert pool not in _customer_ids()


def test_supervisor_sees_their_reports_customers(db_tx, as_actor) -> None:
    reportee_customer = _assigned_to(db_tx, ADMIN)  # priya-nair reports to david-chen
    as_actor(SUPERVISOR)
    assert reportee_customer in _customer_ids()


def test_supervisor_does_not_see_a_team_they_do_not_supervise(db_tx, as_actor) -> None:
    """Scope follows ``teams.supervisor_user_id``, not a shared ``team_id``.

    Supervisors sit in their own team here and oversee others through that
    column. Reading it the obvious way — everyone whose ``team_id`` matches mine
    — would have shown a supervisor their fellow supervisors' customers and
    hidden their actual reports'.
    """
    other_team_customer = _assigned_to(db_tx, AGENT)
    as_actor(SUPERVISOR)
    assert other_team_customer not in _customer_ids()


def test_admin_sees_everything(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    everything = _customer_ids()
    for user in (AGENT, SUPERVISOR, OTHER_AGENT):
        assert visibility.resolve(user).scope != visibility.ALL
    assert _assigned_to(db_tx, AGENT) in everything


# ---------------------------------------------------------------------------
# Coverage — a customer-facing accessor that forgets the marker is unscoped
# ---------------------------------------------------------------------------

#: Accessors that read customer-derived rows, with the kwargs needed to make
#: them return the whole queue rather than a viewer-relative slice.
SCOPED_ACCESSORS = {
    "list_customers": {},
    "list_promises": {},
    "list_callbacks": {},
    "list_disputes": {},
    "list_payment_plans": {},
    "list_leads": {},
    "list_documents": {},
    "list_consent": {},
    "list_work_items": {"assignee": None},
    # Found by test_every_customer_facing_accessor_is_listed rather than by
    # inspection: it was tenant-scoped already, so it did not stand out.
    "list_calls": {},
    # P3. A hold is a collections queue like any other and narrows the same way.
    "list_treatment_holds": {},
    # P5. The case ladder is grouped rather than row-per-record, but it is still
    # borrower data and narrows identically.
    "list_treatment_cases": {},
    # Caught by the same coverage test when the bounce work added it. Scoped by
    # *team*, not by customer book — you claim from your team's unclaimed queue
    # — so it uses its own predicate rather than the shared marker.
    "list_handoff_queue": {},
}


def _row_ids(result: object) -> set[str]:
    """Ids from a list of rows, or from an envelope that carries them.

    The handoff queue returns ``{items, activeInteractionId}``. Normalising the
    shape here keeps the coverage test able to demand every accessor be listed
    without also dictating what each one returns.
    """
    rows: list = []
    if isinstance(result, dict):
        for value in result.values():
            if isinstance(value, list):
                rows.extend(value)
    elif isinstance(result, list):
        rows = result
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("id", "interactionId", "handoffId", "triggerRef"):
            if row.get(key) is not None:
                ids.add(str(row[key]))
    return ids


@pytest.mark.parametrize("accessor", sorted(SCOPED_ACCESSORS))
def test_accessor_narrows_for_an_agent(db_tx, as_actor, accessor: str) -> None:
    """Each accessor must return no more to an agent than to an admin.

    A weaker assertion than naming specific rows, and deliberately so: it holds
    for every accessor without needing a hand-built fixture per screen, which is
    what makes it cheap enough to apply to all of them. The specific-row cases
    above cover the exactness.
    """
    kwargs = SCOPED_ACCESSORS[accessor]
    as_actor(ADMIN)
    admin_rows = _row_ids(getattr(db, accessor)(**kwargs))
    as_actor(OTHER_AGENT)
    agent_rows = _row_ids(getattr(db, accessor)(**kwargs))
    assert agent_rows <= admin_rows, (
        f"{accessor}() returned rows to an agent that an admin does not see — "
        "the scope predicate is inverted or mis-bound"
    )


def test_a_customer_derived_row_is_actually_hidden(db_tx, as_actor) -> None:
    """The sharp version of the above, on a row built for the purpose.

    ``agent_rows <= admin_rows`` passes trivially if an accessor is unscoped and
    both sets are identical, so at least one accessor has to be checked against
    a row that must disappear.
    """
    customer = _assigned_to(db_tx, AGENT)
    db_tx.execute(
        text(
            "INSERT INTO callbacks (id, customer_id, reason, scheduled_at, status) "
            "VALUES ('CB-SCOPE-PROBE', :c, 'scope probe', now(), 'scheduled')"
        ),
        {"c": customer},
    )
    as_actor(AGENT)
    assert "CB-SCOPE-PROBE" in {r["id"] for r in db.list_callbacks()}
    as_actor(OTHER_AGENT)
    assert "CB-SCOPE-PROBE" not in {r["id"] for r in db.list_callbacks()}


def test_every_customer_facing_accessor_is_listed(db_tx) -> None:
    """Fails when a new customer-facing list accessor is not covered here.

    ``_sql()`` leaves an unsubstituted marker as an inert SQL comment, so a
    query that forgets to use it is silently *unscoped*. Nothing syntactic
    catches that — only this.
    """
    import inspect

    customer_screens = {
        name
        for name, fn in inspect.getmembers(db, inspect.isfunction)
        if name.startswith("list_")
        and getattr(fn, "__module__", "") == "db"
        and "customers" in (inspect.getsource(fn) or "")
    }
    missing = customer_screens - set(SCOPED_ACCESSORS)
    assert not missing, (
        "these accessors read customer data and are not covered by the object "
        f"visibility tests: {sorted(missing)}"
    )
