"""Economic configuration as data, resolved env floor → tenant → portfolio.

W8a of docs/design/engines-production-design.md, §13.2. Until this module existed the
engines read their cost book out of the process environment, so
``config_version`` on a decision row was a sha over four environment variables
-- a string that names nothing, and cannot answer *what did a field visit cost
when this decision was made* a week later. Here it names a row.

What this module deliberately does NOT hold
-------------------------------------------
The contact caps, ``LADDER.BUCKET_ACTIONS``, ``LADDER.MAX_RUNG_ADVANCE``,
``FIELD.MIN_EXPOSURE`` and ``VALUE.FLOOR``. Those are ``policy_rules`` rows
with citations, because the cap is the harassment control, the ladder decides
escalation to a field visit and ``VALUE.FLOOR`` decides whether a borrower is
serviced at all. Asked *why did you escalate this borrower to a field visit*,
the answer must be a cited rule, not a config version. What lives where is a
compliance question, not a tidiness question.

Validation is the point, not a nicety
-------------------------------------
:data:`SPEC` is the allowlist and the bounds. A key that is not in it cannot be
written -- a typo'd key that silently persists is the same defect class as a
typo'd arm name that silently renormalises a split. A value outside its bounds
is refused at write, and refused again at read, where it falls back to the
layer beneath rather than being clamped: a cost clamped to zero is still a free
action, and a free action wins every arbitration in ``scoring.py``.

Never raises on the read path
-----------------------------
A resolver that can throw takes the engine down, and an engine that is down
decides nothing for the whole book. Every failure here -- no table, no
database, a malformed row -- degrades to the environment layer, which is the
constant each caller used before this module existed: a known-good state.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from sqlalchemy import text

from env_utils import as_bool, env_bool, env_float, env_int

logger = logging.getLogger(__name__)

#: How long a resolved snapshot is trusted. §13.2 specifies a ``config_epoch``
#: polled every five seconds by every process; a five-second TTL on a lazy
#: re-read converges identically without a thread.
#:
#: ponytail: one query per process per five seconds, and the snapshot is a
#: handful of rows. Upgrade to an epoch-first read -- ``SELECT version FROM
#: config_epoch`` and re-resolve only on a bump -- when the row count makes the
#: full read cost something.
TTL_SECONDS = 5.0

TENANT_LAYER = ""


class ConfigRejected(ValueError):
    """A write that would have corrupted the engine's economics."""


@dataclass(frozen=True)
class Spec:
    """What a key may hold. The whole of write-time validation."""

    kind: str  # float | int | bool | str | json
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] | None = None
    validator: Callable[[Any], Any] | None = None


_MODES = ("off", "shadow", "live")


def _check_variants(value: Any) -> Any:
    """Reject a variant table that would redefine the control arm.

    ``TREATMENT_VARIANTS`` merged over the built-ins, so an operator could
    redefine ``null_treatment`` -- the control arm itself -- from a config
    value, and every incremental number computed afterwards would be measuring
    something else. The built-in arms are not overridable at any layer.
    """
    from agent_core.treatment import config as treatment_config

    if not isinstance(value, Mapping):
        raise ConfigRejected("variants must be a JSON object")
    reserved = set(treatment_config.RESERVED_VARIANTS)
    for name, spec in value.items():
        key = str(name).strip().lower()
        if key in reserved:
            raise ConfigRejected(
                f"variant {key!r} is built in and defines the experiment's arms"
            )
        if not isinstance(spec, Mapping):
            raise ConfigRejected(f"variant {key!r} must be an object")
        arm_mode = str(spec.get("mode") or "").strip().lower()
        if arm_mode and arm_mode not in _MODES:
            raise ConfigRejected(f"variant {key!r} mode {arm_mode!r} is not a mode")
    return dict(value)


def _check_split(value: Any) -> Any:
    """Reject a split naming an arm that does not exist.

    A dropped arm is not a smaller experiment, it is a different one: the
    remaining weights renormalise, so ``arm_probability`` -- which multiplies
    into every logged propensity -- is wrong for every borrower in the book.
    """
    raw = str(value or "").strip()
    if not raw:
        return raw
    from agent_core.treatment import config as treatment_config

    known = set(treatment_config.variants())
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part:
            continue
        name, _, weight = part.partition(":")
        arm = name.strip().lower()
        if arm not in known:
            raise ConfigRejected(f"split names unknown arm {arm!r}")
        if weight.strip():
            try:
                if float(weight) <= 0:
                    raise ConfigRejected(f"split weight for {arm!r} must be positive")
            except ValueError:
                raise ConfigRejected(f"split weight for {arm!r} is not a number") from None
    return raw


def _money(maximum: float) -> Spec:
    """A rupee amount. Negative is not a discount, it is a paid-to-contact bug."""
    return Spec("float", minimum=0.0, maximum=maximum)


#: Every knob an operator may change without a release, and its bounds.
#: Keyed by the environment variable name so one knob has one name, and so the
#: swap at each call site is ``env_float`` → ``number`` and nothing else.
SPEC: dict[str, Spec] = {
    # -- treatment: unit economics -------------------------------------------
    "TREATMENT_COST_SMS": _money(100.0),
    "TREATMENT_COST_WHATSAPP": _money(100.0),
    "TREATMENT_COST_VOICE_BOT": _money(1_000.0),
    "TREATMENT_COST_HUMAN_CALL": _money(5_000.0),
    "TREATMENT_COST_FIELD_VISIT": _money(50_000.0),
    "TREATMENT_COST_LEGAL_NOTICE": _money(100_000.0),
    "TREATMENT_COST_REPRESENT_MANDATE": _money(100.0),
    "TREATMENT_COST_EMI_DATE_CHANGE": _money(5_000.0),
    "TREATMENT_COST_SELF_SERVICE_PLAN": _money(5_000.0),
    # -- treatment: arbitration ----------------------------------------------
    "TREATMENT_MIN_EV": Spec("float", minimum=0.0, maximum=100_000.0),
    "TREATMENT_RECOVERY_FRACTION": Spec("float", minimum=0.0, maximum=1.0),
    "TREATMENT_URGENCY_HALFLIFE_HOURS": Spec("float", minimum=1.0, maximum=8_760.0),
    "TREATMENT_FATIGUE_COST": Spec("float", minimum=0.0, maximum=100_000.0),
    "TREATMENT_MAX_RUNG_ADVANCE": Spec("int", minimum=1, maximum=9),
    "TREATMENT_RESERVE_BUDGET": Spec("bool"),
    "TREATMENT_RESERVE_MARGIN": Spec("float", minimum=1.0, maximum=100.0),
    "TREATMENT_FIELD_DIGITAL_EXHAUSTION": Spec("int", minimum=0, maximum=50),
    "TREATMENT_HORIZON_HOURS": Spec("int", minimum=1, maximum=8_760),
    "TREATMENT_MAX_ATTEMPTS_PER_CASE": Spec("int", minimum=1, maximum=50),
    "TREATMENT_RETRY_BACKOFF_HOURS": Spec("float", minimum=0.0, maximum=8_760.0),
    # -- treatment: runtime ---------------------------------------------------
    "TREATMENT_MODE": Spec("str", choices=_MODES),
    "TREATMENT_SCORER": Spec("str"),
    "TREATMENT_GREEDINESS": Spec("float", minimum=0.0, maximum=1.0),
    "TREATMENT_LOG_VECTORS": Spec("bool"),
    "TREATMENT_MANDATE_EXECUTOR": Spec("str", choices=("rail", "lms")),
    "TREATMENT_VARIANTS": Spec("json", validator=_check_variants),
    "TREATMENT_AB_SPLIT": Spec("str", validator=_check_split),
    # -- treatment: grace windows --------------------------------------------
    "TREATMENT_GRACE_DIGITAL_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_VOICE_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_HUMAN_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_FIELD_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_LEGAL_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_MANDATE_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    "TREATMENT_GRACE_SCHEDULE_HOURS": Spec("float", minimum=0.25, maximum=8_760.0),
    # -- reco: the same rows, read by the other engine (§1462) ---------------
    "RECO_MODE": Spec("str", choices=_MODES),
    "RECO_SCORER": Spec("str"),
    "RECO_LOG_VECTORS": Spec("bool"),
    "RECO_MIN_SCORE": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_MAX_OFFERS": Spec("int", minimum=0, maximum=20),
    "RECO_MAX_PER_CALL": Spec("int", minimum=0, maximum=20),
    "RECO_MAX_PER_CUSTOMER_30D": Spec("int", minimum=0, maximum=100),
    "RECO_DECLINE_COOLDOWN_DAYS": Spec("int", minimum=0, maximum=3_650),
    "RECO_FAMILY_COOLDOWN_DAYS": Spec("int", minimum=0, maximum=3_650),
    "RECO_SENTIMENT_FLOOR": Spec("float", minimum=-1.0, maximum=1.0),
    "RECO_W_AFFINITY": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_AFFORDABILITY": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_CREDIT": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_INTENT": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_SENTIMENT": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_CAMPAIGN": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_FATIGUE": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_W_EXIT_INTENT": Spec("float", minimum=0.0, maximum=1.0),
    "RECO_REQUIRE_COMMITMENT": Spec("bool"),
    "RECO_AB_SPLIT": Spec("str"),
    "RECO_VARIANTS": Spec("json"),
    # -- workers --------------------------------------------------------------
    "TREATMENT_SWEEP_SHARDS": Spec("int", minimum=1, maximum=256),
    "TREATMENT_SWEEP_BATCH": Spec("int", minimum=1, maximum=10_000),
    "TREATMENT_ENACT_BATCH": Spec("int", minimum=1, maximum=10_000),
    "WORKER_POLL_SECONDS": Spec("float", minimum=0.1, maximum=3_600.0),
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def coerce(key: str, value: Any, *, strict: bool = True) -> Any:
    """The stored value for ``key``, or :class:`ConfigRejected`.

    One implementation for both directions: a write is validated before it
    reaches the table, and a value read back is validated again, because the
    bounds may have tightened since it was written.

    ``strict`` is the difference between the two. Bounds always apply -- a
    negative cost is refused wherever it came from. The structural validators
    only run on a write, where an operator is present to be told that their
    document redefines the control arm. On the read path they would take a
    whole variant table down over one bad arm, and the parsers downstream
    already drop a bad arm individually.
    """
    spec = SPEC.get(key)
    if spec is None:
        raise ConfigRejected(f"{key!r} is not a configurable key")

    if spec.kind == "bool":
        # ``as_bool`` returns the default only when it recognised nothing, so
        # two disagreeing defaults mean the value is not a boolean at all.
        # This is the branch that used to be a bare ``bool()``, where the JSON
        # string "false" minted a control arm.
        out: Any = as_bool(value, True)
        if out is not as_bool(value, False):
            raise ConfigRejected(f"{key}={value!r} is not a boolean")
    elif spec.kind in ("float", "int"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ConfigRejected(f"{key}={value!r} is not a number") from None
        # float() parses "nan" and "inf" happily. A NaN cost makes every
        # comparison in the arbitration false; an infinite one makes the
        # action unchoosable. Neither is a configuration.
        if number != number or number in (float("inf"), float("-inf")):
            raise ConfigRejected(f"{key}={value!r} is not finite")
        if spec.kind == "int":
            if float(value) != int(number):
                raise ConfigRejected(f"{key}={value!r} is not a whole number")
            out = int(number)
        else:
            out = number
        if spec.minimum is not None and number < spec.minimum:
            raise ConfigRejected(f"{key}={value!r} is below {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            raise ConfigRejected(f"{key}={value!r} is above {spec.maximum}")
    elif spec.kind == "json":
        out = json.loads(value) if isinstance(value, str) else value
    else:
        out = str(value).strip()
        if spec.choices and out.lower() not in spec.choices:
            raise ConfigRejected(f"{key}={value!r} is not one of {spec.choices}")

    return spec.validator(out) if (strict and spec.validator) else out


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict[str, Any], int | None]] = {}


def invalidate() -> None:
    """Drop cached snapshots. Called after every write, and by tests."""
    with _lock:
        _cache.clear()


def _tenant() -> str:
    import db

    return db._tenant()


def _query(conn: Any, tenant_id: str, portfolio_id: str) -> tuple[dict[str, Any], int | None]:
    epoch = conn.execute(text("SELECT version FROM config_epoch")).scalar()
    rows = (
        conn.execute(
            text(
                """
                SELECT portfolio_id, key, value_json
                  FROM engine_config
                 WHERE tenant_id = :t
                   AND portfolio_id IN (:layer, :p)
                   AND effective @> now()
                 ORDER BY (portfolio_id <> :layer)
                """
            ),
            {"t": tenant_id, "p": portfolio_id, "layer": TENANT_LAYER},
        )
        .mappings()
        .all()
    )
    # Tenant rows first, portfolio rows second, so the narrower scope wins by
    # arriving last. Same order the ORDER BY produces.
    resolved: dict[str, Any] = {}
    for row in rows:
        key = str(row["key"])
        try:
            resolved[key] = coerce(key, row["value_json"], strict=False)
        except ConfigRejected as exc:
            # A row that no longer satisfies its own spec is not clamped into
            # range -- a cost clamped to zero is still a free action, and a
            # free action wins every arbitration. It falls through to the
            # environment layer, which is where it was before this table.
            logger.warning("engine_config row ignored: %s", exc)
    return resolved, (int(epoch) if epoch is not None else None)


def _guarded(conn: Any, tenant_id: str, portfolio_id: str) -> tuple[dict[str, Any], int | None]:
    """:func:`_query` inside a savepoint, degrading to the environment layer.

    The failure this most often takes is ``relation "config_epoch" does not
    exist`` on a database where 0116 has not been applied. A failed statement
    aborts the whole enclosing transaction -- here, the one the decision row is
    written on -- so the savepoint is not tidiness, it is the difference
    between a config miss and a lost decision. W0's rule: a savepoint at every
    lent-connection boundary.
    """
    savepoint = None
    try:
        savepoint = conn.begin_nested()
        resolved = _query(conn, tenant_id, portfolio_id)
        savepoint.commit()
        return resolved
    except Exception:
        logger.debug("engine_config unresolved — using the environment", exc_info=True)
        if savepoint is not None:
            try:
                savepoint.rollback()
            except Exception:
                logger.debug("engine_config savepoint rollback failed", exc_info=True)
        return {}, None


def snapshot(
    tenant_id: str | None = None,
    portfolio_id: str = TENANT_LAYER,
    *,
    conn: Any = None,
) -> tuple[dict[str, Any], int | None]:
    """The resolved config layer and the epoch it was read at.

    Pass ``conn`` on any path that already holds a transaction --
    ``treatment/engine.py`` states as an invariant that it never opens its own
    connection, and a second connection inside a decision is a deadlock waiting
    for load. A lent connection also sees the caller's uncommitted writes,
    which is what makes this testable inside the ``db_tx`` savepoint fixture.
    Reads on a lent connection are not cached: the caller's transaction is the
    truth, and it can change under us.

    Empty on any failure. Callers then see exactly the environment they saw
    before this module existed.
    """
    tenant = str(tenant_id or "") or _tenant()
    scope = (tenant, portfolio_id or TENANT_LAYER)

    if conn is not None:
        return _guarded(conn, scope[0], scope[1])

    now = time.monotonic()
    with _lock:
        hit = _cache.get(scope)
        if hit is not None and hit[0] > now:
            return hit[1], hit[2]

    try:
        import db

        with db.engine.connect() as own:
            # Also guarded. ``db.engine`` is not always a real engine: the
            # ``db_tx`` test fixture proxies ``connect()`` back to the one
            # shared connection the test is running in, so this branch can be
            # a lent connection too, and an unguarded miss here aborts the
            # test's transaction rather than its own.
            resolved, epoch = _guarded(own, scope[0], scope[1])
    except Exception:
        # No table yet, no database at all: the environment is the floor and
        # it is always readable.
        logger.debug("engine_config unresolved — using the environment", exc_info=True)
        resolved, epoch = {}, None

    with _lock:
        _cache[scope] = (time.monotonic() + TTL_SECONDS, resolved, epoch)
    return resolved, epoch


def _layered(key: str, portfolio_id: str, conn: Any = None) -> Any:
    resolved, _ = snapshot(portfolio_id=portfolio_id, conn=conn)
    return resolved.get(key)


def number(
    key: str,
    default: float,
    *,
    portfolio_id: str = TENANT_LAYER,
    conn: Any = None,
) -> float:
    """A float knob. Same signature as ``env_utils.env_float``, plus a scope."""
    found = _layered(key, portfolio_id, conn)
    if found is not None:
        return float(found)
    return _validated_env(key, env_float(key, default), default)


def integer(
    key: str,
    default: int,
    *,
    portfolio_id: str = TENANT_LAYER,
    conn: Any = None,
) -> int:
    found = _layered(key, portfolio_id, conn)
    if found is not None:
        return int(found)
    return int(_validated_env(key, env_int(key, default), default))


def flag(
    key: str,
    default: bool = False,
    *,
    portfolio_id: str = TENANT_LAYER,
    conn: Any = None,
) -> bool:
    found = _layered(key, portfolio_id, conn)
    if found is not None:
        return bool(found)
    return env_bool(key, default)


def text_value(
    key: str,
    default: str,
    *,
    portfolio_id: str = TENANT_LAYER,
    conn: Any = None,
) -> str:
    """A string knob, validated against its spec's choices in both layers."""
    found = _layered(key, portfolio_id, conn)
    if found is not None:
        return str(found)
    import os

    value = (os.getenv(key) or "").strip()
    if not value:
        return default
    return str(_validated_env(key, value, default))


def raw(
    key: str,
    default: Any = None,
    *,
    portfolio_id: str = TENANT_LAYER,
    conn: Any = None,
) -> Any:
    """A structured knob (``json``), or the environment string behind it."""
    found = _layered(key, portfolio_id, conn)
    if found is not None:
        return found
    import os

    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    try:
        return coerce(key, value, strict=False)
    except (ConfigRejected, json.JSONDecodeError) as exc:
        logger.warning("%s ignored: %s", key, exc)
        return default


def _validated_env(key: str, value: Any, default: Any) -> Any:
    """Hold the environment layer to the same bounds as a row.

    The environment was never validated before this module: a negative
    ``TREATMENT_COST_FIELD_VISIT`` went straight into ``ev = gross - cost``
    and made a doorstep visit profitable. It goes through the same spec now.
    """
    if value == default or key not in SPEC:
        # A key with no spec behaves exactly as it did before this module --
        # unvalidated, but working. Swallowing it here would silently disable
        # every environment override somebody forgot to add to SPEC, which is
        # the same class of silent failure the spec exists to end.
        return value
    try:
        return coerce(key, value, strict=False)
    except ConfigRejected as exc:
        logger.warning("environment override ignored: %s", exc)
        return default


def version(portfolio_id: str = TENANT_LAYER, *, conn: Any = None) -> str | None:
    """``cfg:<epoch>`` when configuration resolved to rows, else ``None``.

    ``None`` is the honest answer on a database where nobody has written a
    config row: ``cfg:1`` would name an empty result, and W8's exit criterion
    is that ``config_version`` *resolves* to a row. The caller
    (``logging_contract.config_version``) falls back to W2's environment sha.
    """
    resolved, epoch = snapshot(portfolio_id=portfolio_id, conn=conn)
    if not resolved or epoch is None:
        return None
    return f"cfg:{epoch}"


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------


def put(
    conn: Any,
    key: str,
    value: Any,
    *,
    tenant_id: str,
    changed_by: str,
    approved_by: str,
    reason: str,
    portfolio_id: str = TENANT_LAYER,
) -> int:
    """Supersede one key in one scope. Returns the new epoch.

    Raises :class:`ConfigRejected` before touching the database. Maker-checker
    is a CHECK on the table, not a convention here -- this function cannot
    smuggle a self-approval past it.
    """
    stored = coerce(key, value)
    if not str(reason or "").strip():
        raise ConfigRejected("a config change carries a reason")

    scope = {"t": tenant_id, "p": portfolio_id or TENANT_LAYER, "k": key}
    # Within one transaction ``now()`` does not advance, so a row opened in
    # this same transaction cannot be closed at ``now()`` -- the range would be
    # empty and the CHECK would reject it. Replace it instead: it never existed
    # outside this transaction, so there is no history to preserve.
    conn.execute(
        text(
            "DELETE FROM engine_config"
            " WHERE tenant_id = :t AND portfolio_id = :p AND key = :k"
            "   AND lower(effective) >= now()"
        ),
        scope,
    )
    conn.execute(
        text(
            "UPDATE engine_config"
            "   SET effective = tstzrange(lower(effective), now())"
            " WHERE tenant_id = :t AND portfolio_id = :p AND key = :k"
            "   AND upper(effective) IS NULL"
        ),
        scope,
    )
    epoch = conn.execute(
        text(
            "UPDATE config_epoch SET version = version + 1, bumped_at = now()"
            " RETURNING version"
        )
    ).scalar()
    conn.execute(
        text(
            """
            INSERT INTO engine_config (
              id, tenant_id, portfolio_id, key, value_json, effective,
              version, changed_by, approved_by, reason
            ) VALUES (
              :id, :t, :p, :k, CAST(:v AS jsonb), tstzrange(now(), NULL),
              :version, :changed_by, :approved_by, :reason
            )
            """
        ),
        {
            **scope,
            "id": f"CFG-{key}-{epoch}-{portfolio_id or 'tenant'}"[:120],
            "v": json.dumps(stored),
            "version": epoch,
            "changed_by": changed_by,
            "approved_by": approved_by,
            "reason": reason,
        },
    )
    invalidate()
    return int(epoch)
