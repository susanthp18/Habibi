"""Money formatting. One implementation, imported from both sides.

The deployment shows, writes and speaks Vietnamese đồng (``CURRENCY``). It was
Indian rupees until the Vietnam deployment (2026-10-08); stored amounts were not
converted, only their rendering changed. The module keeps its historical name,
and the rupee notes below explain why there is a single owner at all.

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

from decimal import ROUND_HALF_UP, Decimal

#: What a null amount reads as. Not "0 ₫" — an amount nobody has is not zero.
NULL_DISPLAY = "—"

#: The deployment's currency. Mirrors Habibi/src/lib/format.ts::CURRENCY:
#: change one, change both.
CURRENCY = "VND"
SYMBOL = "₫"
#: vi-VN writes the symbol after the number behind a no-break space, and so
#: does the client's Intl.NumberFormat("vi-VN"): "45.000 ₫".
_NBSP = "\u00a0"

PAISA = Decimal("0.01")


def amount(value: object) -> Decimal:
    """A rupee amount as the ledger stores it: exact, to the paisa.

    The ledger columns are ``numeric(14,2)``. Comparing a cap against a
    request as floats needed a ``0.009`` slop to survive ``0.1 + 0.2``, and the
    slop let a request half a paisa over the cap through. There is no half
    paisa: round to the column's precision and compare exactly.
    """
    return Decimal(str(value if value is not None else 0)).quantize(PAISA, rounding=ROUND_HALF_UP)


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


def group_vi(digits: str) -> str:
    """Vietnamese digit separators: a dot every three (1234567 -> 1.234.567)."""
    return f"{int(digits):,}".replace(",", ".")


def spoken_money(amount: object, currency: str | None = CURRENCY) -> str | None:
    """A whole amount with its currency, as an agent says it to the customer.

    Rupees keep the symbol and lakh grouping (₹12,50,000); any other currency
    is its ISO code with Western grouping (AED 12,500), which every voice reads
    correctly. None when there is no amount.
    """
    try:
        whole = abs(int(round(float(amount))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    code = (currency or CURRENCY).upper()
    if code == "INR":
        return f"₹{group_indian(str(whole))}"
    return f"{code} {whole:,}"


def inr(amount: float | None, *, none: str = NULL_DISPLAY) -> str:
    """Whole đồng the way vi-VN writes it: "1.234.567 ₫", "-500 ₫".

    Character for character what the client's ``fmtMoney`` prints with
    ``Intl.NumberFormat("vi-VN", {style: "currency", currency: "VND"})``, so a
    work item's detail line and the amount column beside it agree. Collections
    balances go negative after an overpay, so the sign case is reachable.

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
    return f"{sign}{group_vi(str(abs(whole)))}{_NBSP}{SYMBOL}"


# --- compact ---------------------------------------------------------------
# The ladder below is shared with Habibi/src/data/billing-seed.ts::inrCompact.
# Change one, change both — they are read side by side on the billing screen,
# where the Python value labels a chart the TypeScript value axis-labels.

#: Below this, a nonzero value cannot be shown to four decimals and is floored
#: to a "smaller than" reading rather than to a plausible-looking zero.
COMPACT_EPSILON = 0.0001


def template_amount(amount: object) -> str:
    """Đồng for an SMS or a pay-link template, without the symbol (the copy
    carries it). vi-VN grouping -- "1.234.567" -- because this is the number
    the borrower reads. A fraction is kept only when there is one, after a
    decimal comma ("1.500,50"); a template slot reads better as "1.500" than
    "1.500,00".
    """
    try:
        n = Decimal(str(amount)).quantize(PAISA)
    except Exception:
        return str(amount)
    whole = group_vi(str(abs(int(n))))
    sign = "-" if n < 0 else ""
    if n == n.to_integral():
        return f"{sign}{whole}"
    fraction = f"{abs(n) % 1:.2f}"[2:]
    return f"{sign}{whole},{fraction}"


#: vi-VN's compact suffixes: nghìn, triệu, tỷ, nghìn tỷ.
_COMPACT_STEPS = ((10**12, "NT"), (10**9, "T"), (10**6, "Tr"), (10**3, "N"))


def _compact_magnitude(value: float) -> str:
    """One decimal, half away from zero, trailing ",0" dropped, and a value
    that rounds up to 1000 of a suffix promoted to the next one -- what
    ``Intl.NumberFormat("vi-VN", {notation: "compact",
    maximumFractionDigits: 1})`` does: 999_960 -> "1 Tr", not "1000 N"."""
    exact = Decimal(value)
    for i, (div, suffix) in enumerate(_COMPACT_STEPS):
        if exact < div:
            continue
        q = (exact / div).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if q >= 1000 and i > 0:
            up_div, suffix = _COMPACT_STEPS[i - 1]
            q = (exact / up_div).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        text = f"{q:f}".removesuffix(".0").replace(".", ",")
        return f"{text}{_NBSP}{suffix}{_NBSP}{SYMBOL}"
    raise ValueError("below the compact range")


def inr_compact(amount: float | None) -> str:
    """Compact đồng. The canonical ladder, matching the client exactly.

    ::

        0                 -> "0 ₫"
        0 < n < 0.0001    -> "<0,0001 ₫"
        0.0001 <= n < 1   -> "0,0040 ₫"   (4 dp)
        1 <= n < 1_000    -> "12,50 ₫"    (2 dp)
        n >= 1_000        -> "1,5 N ₫", "12,3 Tr ₫", "4,5 T ₫" (vi-VN compact)
        negative          -> "-" + the same

    (Every space above is a no-break space, as Intl prints it.)

    The sub-1 branches are the reason this is not a one-liner. Per-call
    metering produces genuinely tiny amounts, and ``main.py`` says in as many
    words that a call with no attributed usage must not be shown as a genuine
    zero. Rounding a real, billed 0.0040 of LLM spend to "0" would make it
    indistinguishable from a call that cost nothing.
    """
    value = float(amount or 0)
    if value < 0:
        return f"-{inr_compact(-value)}"
    if value >= 1_000:
        return _compact_magnitude(value)
    if value >= 1:
        return f"{value:.2f}".replace(".", ",") + f"{_NBSP}{SYMBOL}"
    if value >= COMPACT_EPSILON:
        return f"{value:.4f}".replace(".", ",") + f"{_NBSP}{SYMBOL}"
    if value > 0:
        # Real spend, too small to render. Saying so beats rounding it away.
        return f"<{COMPACT_EPSILON:.4f}".replace(".", ",") + f"{_NBSP}{SYMBOL}"
    return f"0{_NBSP}{SYMBOL}"
