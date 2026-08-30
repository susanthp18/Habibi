"""Strata for segment-level uplift — §9's granularity ladder, as a partition.

τ is the *difference* of two noisy quantities, so it needs an order of magnitude
more data than a response model. A client with a 50k book at 5% delinquency
generates ~2,500 delinquent accounts a month; split across seven actions and
stratified, that will never support per-account CATE. Jumping there anyway
produces confident noise, which is strictly worse than the current priors
because it *looks* learned.

So the ladder goes population → segment → individual, and each rung is climbed
only when the holdout says the finer model beat the coarser one. This module is
the middle rung: it defines what a segment *is*.

**The key is computed from the logged vector, never from today's tables.** That
is the same point-in-time discipline the trainers already enforce, and it
matters more here than anywhere else: a borrower who was 45 DPD in March is 120
DPD now, and scoring March's decision against today's bucket would place it in a
stratum it was never in. :func:`key_for` therefore takes a vector and nothing
else, so an offline replay and a live decision cannot disagree.

**Deliberately coarse.** Three dimensions, thirty cells at most, and in practice
the holdout gate keeps a handful. The temptation is to cross every dimension the
design note lists and end up with four hundred cells holding nine observations
each, which is individual CATE wearing a segment's name.

**Channel is not a dimension, and that is a choice worth defending.** The design
note lists segments as "bucket × channel × contactability × cash-flow pattern".
Channel is left out because the action is already a feature *inside* each
segment's model — ``rung``, ``intrusiveness`` and ``connect_rate_channel`` are
all in the vector — so channel heterogeneity is captured by the model rather
than by the partition. Partitioning on it as well would triple the cell count to
learn something the model can already express, and every cell would hold a third
of the data.
"""

from __future__ import annotations

from typing import Mapping

#: Bump when the banding changes. An artifact fitted under one version cannot
#: have its segments applied under another — the keys would collide while
#: meaning different populations, which is the worst kind of silent wrong.
SEGMENT_VERSION = "s1"

#: The cell for a borrower we cannot place. Never fitted, never promoted: a
#: model for "the rows whose DPD was missing" is a model of a data-quality
#: incident, and it would be applied to whichever accounts happen to be broken
#: on the day it is scored.
UNKNOWN = "unknown"

# --- dimension 1: bucket ----------------------------------------------------
# Delinquency stage, because curability collapses across it and so does the
# effect of contacting at all. The bands match the buckets the rest of the
# package already uses, so a segment is nameable in a floor conversation.
_BUCKETS: tuple[tuple[float, str], ...] = (
    (0.0, "predue"),
    (30.0, "b0030"),
    (60.0, "b3160"),
    (90.0, "b6190"),
)
_BUCKET_TAIL = "b90p"

# --- dimension 2: contactability -------------------------------------------
#: Digital attempts since the last real connect. The cleanest available proxy
#: for "can we still get through to this person", and it is in every vector
#: because it is what the ladder itself is driven by.
#:
#: Two bands, not four. The interesting split is reachable-vs-going-dark, and a
#: borrower who has absorbed three unanswered digital attempts is already in the
#: second group; finer bands would only separate degrees of the same answer.
CONTACT_DARK_THRESHOLD = 3.0

# --- dimension 3: cash-flow pattern ----------------------------------------
#: Why the money is not arriving, which is the discriminator §5 is built around
#: and the one the return code hands us for free.
#:
#: ``timing``     — the money exists, it arrived on the wrong day
#: ``capacity``   — the money is not there
#: ``mechanism``  — the rail is broken, not the borrower
#:
#: These three want genuinely different interventions, and a τ estimated across
#: them is an average of three unrelated effects.
CASHFLOW_TIMING = "timing"
CASHFLOW_CAPACITY = "capacity"
CASHFLOW_MECHANISM = "mechanism"

#: A salary landing within this many days either side of the debit is a timing
#: story rather than a capacity one. Deliberately wider than
#: ``policy.EMI_TIMING_TOLERANCE_DAYS``: that constant gates an action, this one
#: only decides which pile to learn from, and being wrong here costs precision
#: rather than a wrongly-suppressed intervention.
SALARY_GAP_TIMING_DAYS = 7.0


def _num(vec: Mapping[str, float | None], key: str) -> float | None:
    raw = vec.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def bucket_band(vec: Mapping[str, float | None]) -> str | None:
    dpd = _num(vec, "dpd")
    if dpd is None:
        return None
    for edge, name in _BUCKETS:
        if dpd <= edge:
            return name
    return _BUCKET_TAIL


def contact_band(vec: Mapping[str, float | None]) -> str:
    """``open`` or ``dark``. Absent evidence reads as ``open``, on purpose.

    A borrower we have never attempted has no unanswered attempts, and treating
    "we have not tried" as "they do not answer" would file every new account
    into the hard-to-reach stratum on its first decision.
    """
    attempts = _num(vec, "digital_attempts_since_connect") or 0.0
    return "dark" if attempts >= CONTACT_DARK_THRESHOLD else "open"


def cashflow_band(vec: Mapping[str, float | None]) -> str:
    """Timing, capacity or mechanism — read off the return code where we have one.

    The return code is believed over the salary gap when both are present. A
    bank telling us the mandate is cancelled is a fact; a salary-timing gap
    inferred from credit history is an estimate, and an estimate does not
    overrule an observation.
    """
    for flag in ("bounce_mandate_expired", "bounce_account_closed", "bounce_technical"):
        if (_num(vec, flag) or 0.0) > 0.5:
            return CASHFLOW_MECHANISM
    gap = _num(vec, "salary_timing_gap_days")
    if gap is not None and abs(gap) <= SALARY_GAP_TIMING_DAYS:
        return CASHFLOW_TIMING
    return CASHFLOW_CAPACITY


def key_for(vec: Mapping[str, float | None]) -> str:
    """The stratum this decision belongs to, e.g. ``b0030/open/timing``.

    Never raises and never returns an empty string: this runs inside
    :meth:`models.ModelArtifact.predict`, which sits on the audio path of a live
    call, and a segment lookup is not worth a failed decision.
    """
    try:
        bucket = bucket_band(vec)
        if bucket is None:
            return UNKNOWN
        return f"{bucket}/{contact_band(vec)}/{cashflow_band(vec)}"
    except Exception:  # pragma: no cover - defensive
        return UNKNOWN


def describe(key: str) -> str:
    """A floor-readable name for a segment key, for reports and model cards."""
    if key == UNKNOWN:
        return "unplaceable (no DPD on the logged vector)"
    parts = key.split("/")
    if len(parts) != 3:
        return key
    bucket, contact, cash = parts
    bucket_label = {
        "predue": "pre-due",
        "b0030": "0-30 DPD",
        "b3160": "31-60 DPD",
        "b6190": "61-90 DPD",
        "b90p": "90+ DPD",
    }.get(bucket, bucket)
    contact_label = {"open": "reachable", "dark": "going dark"}.get(contact, contact)
    cash_label = {
        CASHFLOW_TIMING: "salary-timing",
        CASHFLOW_CAPACITY: "capacity",
        CASHFLOW_MECHANISM: "broken rail",
    }.get(cash, cash)
    return f"{bucket_label}, {contact_label}, {cash_label}"


def all_keys() -> tuple[str, ...]:
    """Every key the partition can emit, excluding :data:`UNKNOWN`.

    Enumerable on purpose: a segment map carrying a key not in this set was
    fitted under a different banding, and loading it would apply March's
    partition to August's book.
    """
    buckets = [name for _, name in _BUCKETS] + [_BUCKET_TAIL]
    return tuple(
        f"{b}/{c}/{f}"
        for b in buckets
        for c in ("open", "dark")
        for f in (CASHFLOW_TIMING, CASHFLOW_CAPACITY, CASHFLOW_MECHANISM)
    )
