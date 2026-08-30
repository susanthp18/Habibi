"""Indian rupee formatting. One implementation, imported from both sides.

A leaf module on purpose: it imports nothing from this repo, so ``db.py`` and
``agent_core`` can both take it at module level without closing a cycle.
``agent_core/__init__`` eagerly imports ``deployment``, which does ``import db``,
so anything that lives on either side of that edge and is wanted by the other
has to sit below both. ``pg_errors``, ``env_utils``, ``tenant_context`` and
``visibility`` are here for the same reason.

It exists because seven functions were formatting rupees seven ways, and six of
them used Python's Western grouping. That is not cosmetic:

* ``agent_core/context.py`` builds the customer card that goes into the agent's
  system prompt, so the model was reading — and speaking — "one million two
  hundred thirty four thousand" shaped numbers to Indian borrowers.
* ``agent_core/authority/talk.py`` writes the goodwill-waiver line the agent
  quotes to the customer.
* ``agent_core/treatment/narrate.py`` and ``scoring.py`` write the decision-log
  narration, which is the audit artefact for why an action was taken — and both
  managed to mix two different formats inside a single sentence.

Meanwhile ``db.py`` serialises the same amounts for a client that renders them
with ``toLocaleString("en-IN")``. The two disagreed one row apart.
"""

from __future__ import annotations

#: What a null amount reads as. Not "₹0" — an amount nobody has is not zero.
NULL_DISPLAY = "—"


def group_indian(digits: str) -> str:
    """Insert Indian digit separators into a string of digits.

    Last three, then twos: 1234567 -> 12,34,567. Takes and returns bare digits
    so the callers can decide about signs, symbols and decimals.
    """
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def inr(amount: float | None, *, none: str = NULL_DISPLAY) -> str:
    """Indian digit grouping — ₹12,34,567, not Python's Western ₹1,234,567.

    ``f"{x:,.0f}"`` cannot express lakh/crore grouping at all, so a work-item's
    detail column printed "Promised ₹1,234,567" directly beside an amount
    column the client renders with ``toLocaleString("en-IN")`` as "₹12,34,567":
    the same number, grouped two different ways, one row apart.

    The sign sits *inside* the symbol ("₹-500") because that is exactly what
    ``"₹" + (-500).toLocaleString("en-IN")`` yields on the client, and the point
    of this function is that the two agree. Collections balances go negative
    after an overpay, so the case is reachable rather than theoretical.

    ``none`` exists because the call sites genuinely disagree about the empty
    case and both are right: a table cell wants an em dash, while a sentence
    being concatenated ("Goodwill ceiling is …") wants nothing at all.
    """
    if amount is None:
        return none
    try:
        whole = int(round(float(amount)))
    except (TypeError, ValueError):
        return none
    sign = "-" if whole < 0 else ""
    return f"₹{sign}{group_indian(str(abs(whole)))}"


# --- compact ---------------------------------------------------------------
# The ladder below is shared with Habibi/src/data/billing-seed.ts::inrCompact.
# Change one, change both — they are read side by side on the billing screen,
# where the Python value labels a chart the TypeScript value axis-labels.

#: Below this, a nonzero value cannot be shown to four decimals and is floored
#: to a "smaller than" reading rather than to a plausible-looking zero.
COMPACT_EPSILON = 0.0001


def inr_compact(amount: float | None) -> str:
    """Compact Indian money. The canonical ladder, matching the client exactly.

    ::

        0                     -> "₹0"
        0 < n < 0.0001        -> "<₹0.0001"
        0.0001 <= n < 1       -> "₹0.0040"     (4 dp)
        1 <= n < 1_000        -> "₹12.50"      (2 dp)
        1_000 <= n < 1_00_000 -> "₹1.5k"       (lowercase k, no space)
        1_00_000 <= n < 1cr   -> "₹12.3L"
        n >= 1_00_00_000      -> "₹4.5Cr"
        negative              -> "-" + the same

    One decimal on every magnitude suffix, so the three read as one ladder
    rather than three conventions. Two decimals on a crore figure is six
    significant digits of precision in a label whose whole job is to be
    glanceable.

    The sub-rupee branches are the reason this is not a one-liner. Per-call
    metering produces genuinely tiny amounts, and ``main.py`` says in as many
    words that a call with no attributed usage "must not be shown as a genuine
    ₹0.00". The old Python ladder did exactly that: it formatted anything under
    ₹1000 with ``f"₹{value:,.0f}"``, so ₹0.0040 of real, billed LLM spend
    rendered as "₹0" — indistinguishable from a call that cost nothing.
    """
    value = float(amount or 0)
    if value < 0:
        return f"-{inr_compact(-value)}"
    if value >= 1_00_00_000:
        return f"₹{value / 1_00_00_000:.1f}Cr"
    if value >= 1_00_000:
        return f"₹{value / 1_00_000:.1f}L"
    if value >= 1_000:
        return f"₹{value / 1_000:.1f}k"
    if value >= 1:
        return f"₹{value:.2f}"
    if value >= COMPACT_EPSILON:
        return f"₹{value:.4f}"
    if value > 0:
        # Real spend, too small to render. Saying so beats rounding it away.
        return f"<₹{COMPACT_EPSILON:.4f}"
    return "₹0"
