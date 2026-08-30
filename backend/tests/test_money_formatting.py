"""One rupee format across the server/client seam.

The AssignedQueue row is the reason this file exists. Its amount column is
rendered by the client as ``"₹" + amount.toLocaleString("en-IN")``; its detail
column is a *string the server already baked* ("Promised …", "Disputed …").
Those two cells sit one column apart on the same row, so any disagreement
between Python's formatting and ICU's en-IN grouping is visible without
scrolling — and ``f"{x:,.0f}"`` disagrees on every number above 99,999, because
Python's ``,`` only knows Western thousands grouping.

The ``expected`` strings below are not hand-derived. They are the literal
output of ``"₹" + Number(v).toLocaleString("en-IN")`` in node, which is the
same ICU data the browser uses, so a passing test here is a statement about
the two renderings agreeing rather than about one implementation's opinion.
"""

from __future__ import annotations

import pytest

import db


# (value, exactly what the client prints for the same value)
GROUPING_CASES = [
    (0, "₹0"),
    (999, "₹999"),
    (1_000, "₹1,000"),
    (9_999, "₹9,999"),
    (100_000, "₹1,00,000"),
    (999_999, "₹9,99,999"),
    (1_000_000, "₹10,00,000"),
    (1_234_567, "₹12,34,567"),
    (10_000_000, "₹1,00,00,000"),
    (-999, "₹-999"),
    (-1_234_567, "₹-12,34,567"),
]


@pytest.mark.parametrize("value, expected", GROUPING_CASES)
def test_inr_groups_the_indian_way(value, expected):
    """Lakh/crore grouping at every place-value boundary that changes shape."""
    assert db._inr(value) == expected


def test_inr_keeps_the_em_dash_for_a_missing_amount():
    """Not every work item has an amount; "—" is the column's empty state."""
    assert db._inr(None) == "—"


def test_inr_rounds_to_whole_rupees():
    """The detail column is prose, not a ledger — paise would only add noise."""
    assert db._inr(1_234_567.4) == "₹12,34,567"
    assert db._inr(99_999.6) == "₹1,00,000"


def test_inr_does_not_render_negative_zero():
    """A balance that rounds away to nothing is "₹0", never "₹-0"."""
    assert db._inr(-0.4) == "₹0"


def test_inr_carries_the_sign_inside_the_symbol():
    """Matches ``"₹" + (-500).toLocaleString("en-IN")`` → "₹-500".

    Typographically "-₹500" reads better, but the client builds its string by
    concatenating the symbol onto the formatted number and this module is not
    allowed to disagree with it. Overpaid accounts make this reachable.
    """
    assert db._inr(-500).startswith("₹-")


def test_work_item_detail_strings_group_the_same_way_as_the_amount_column():
    """The original defect, at the level the user actually sees it.

    Both halves of the row are built here from one value: the detail string the
    server ships, and the client's rendering of the amount alongside it. Before
    the fix these read "Promised ₹1,234,567" and "₹12,34,567".
    """
    amount = 1_234_567.0
    client_amount_cell = "₹12,34,567"  # node: "₹" + (1234567).toLocaleString("en-IN")

    assert f"Promised {db._inr(amount)}" == f"Promised {client_amount_cell}"
    assert f"Disputed {db._inr(amount)}" == f"Disputed {client_amount_cell}"
    assert (
        f"Paid {db._inr(200_000.0)} of {db._inr(amount)} promised"
        == f"Paid ₹2,00,000 of {client_amount_cell} promised"
    )


# ---------------------------------------------------------------------------
# The shared module, and the call sites that used to disagree with it.
#
# Six modules carried their own _inr, five of them emitting Western grouping,
# and two of those five feed text a customer hears: the agent's system prompt
# (agent_core/context.py) and the goodwill-waiver line it speaks
# (agent_core/authority/talk.py). money_inr is the single implementation they
# all now delegate to; these assert each seam separately, because a shared
# helper that one caller has quietly stopped using is not shared.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value, expected", GROUPING_CASES)
def test_the_shared_module_is_what_db_delegates_to(value, expected):
    import money_inr

    assert money_inr.inr(value) == expected
    assert db._inr(value) == money_inr.inr(value)


def test_the_shared_module_is_a_leaf():
    """It must import nothing from this repo, or it cannot serve both sides.

    ``agent_core/__init__`` eagerly imports ``deployment``, which imports
    ``db``. A shared helper that reached back into either side would close that
    loop the first time the other side imported it.
    """
    import ast
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "money_inr.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    # __future__ is the only import it is allowed to have.
    assert [m for m in imported if m != "__future__"] == []


def test_the_null_reading_is_per_call_site():
    """A table cell wants an em dash; a spoken sentence wants nothing."""
    import money_inr

    assert money_inr.inr(None) == "—"
    assert money_inr.inr(None, none="") == ""


def test_the_agent_prompt_card_groups_the_indian_way():
    """This string goes into the model's system prompt and gets spoken."""
    from agent_core import context

    assert context._inr(1_234_567) == "₹12,34,567"
    # Unusable values are dropped from the card rather than rendered as a dash.
    assert context._inr(None) is None
    assert context._inr("not a number") is None


def test_the_goodwill_talk_track_groups_the_indian_way():
    """The agent quotes this figure to the customer."""
    from agent_core.authority import talk
    from agent_core.authority.matrix import MatrixDecision, VERDICT_AUTO

    line = talk.talk_track(
        MatrixDecision(
            verdict=VERDICT_AUTO,
            approved_amount=1_234_567,
            cap_amount=None,
            reason="",
            reason_codes=(),
        )
    )
    assert "₹12,34,567" in line
    assert "1,234,567" not in line


def test_the_customer_insight_label_groups_the_indian_way():
    """Also the site of a no-op ``.replace(",", ",")`` that did nothing."""
    import customer_insights

    assert customer_insights._inr(1_234_567) == "₹12,34,567"


def test_the_offer_insight_label_uses_the_shared_formatter():
    import customer_insights

    nba = customer_insights._offer_nba(
        {"status": "ready", "productName": "Top-up loan", "suggestedAmount": 1_234_567}
    )
    assert nba is not None
    assert "₹12,34,567" in nba["title"]


def test_the_treatment_narration_carries_one_money_format():
    """The decision log's explanation of why an action was taken.

    It used to print ``₹4.50`` and ``₹1,234,567`` inside a single sentence.
    """
    from agent_core.treatment import narrate

    assert narrate._inr(1_234_567) == "₹12,34,567"


def test_the_scoring_explanation_carries_one_money_format():
    from agent_core.treatment.scoring import EVScorer

    line = EVScorer._explain(
        object.__new__(EVScorer),
        "whatsapp",
        ev=1_234_567,
        reach=0.5,
        resolve=0.25,
        cost=4.5,
        fatigue=0.0,
    )
    assert "₹12,34,567" in line
    assert "₹4.50" in line
    assert "1,234,567" not in line


# ---------------------------------------------------------------------------
# The compact ladder. This table is mirrored byte-for-byte in
# Habibi/src/data/billing-seed.test.ts — change one, change both.
# ---------------------------------------------------------------------------

COMPACT_CASES = [
    (0, "₹0"),
    (0.00004, "<₹0.0001"),
    (0.0001, "₹0.0001"),
    (0.004, "₹0.0040"),
    (0.9999, "₹0.9999"),
    (1, "₹1.00"),
    (12.5, "₹12.50"),
    (999.99, "₹999.99"),
    (1_000, "₹1.0k"),
    (1_500, "₹1.5k"),
    (99_999, "₹100.0k"),
    (1_00_000, "₹1.0L"),
    (12_34_567, "₹12.3L"),
    (99_99_999, "₹100.0L"),
    (1_00_00_000, "₹1.0Cr"),
    (4_50_00_000, "₹4.5Cr"),
]


@pytest.mark.parametrize("value, expected", COMPACT_CASES)
def test_inr_compact_ladder(value, expected):
    import money_inr

    assert money_inr.inr_compact(value) == expected
    assert db._inr_compact(value) == expected


@pytest.mark.parametrize("value, expected", [c for c in COMPACT_CASES if c[0] != 0])
def test_inr_compact_mirrors_the_ladder_for_negatives(value, expected):
    import money_inr

    assert money_inr.inr_compact(-value) == f"-{expected}"


@pytest.mark.parametrize("tiny", [0.00009, 0.000001, 1e-12])
def test_inr_compact_never_shows_real_spend_as_a_genuine_zero(tiny):
    """main.py says a metering gap "must not be shown as a genuine ₹0.00".

    The old ladder formatted everything under ₹1000 with ``f"₹{v:,.0f}"``, so a
    call that really cost ₹0.004 of LLM tokens rendered as "₹0" — the same
    string as a call that was never metered at all.
    """
    import money_inr

    assert money_inr.inr_compact(tiny) == "<₹0.0001"
    assert money_inr.inr_compact(tiny) != "₹0"


def test_inr_compact_uses_lowercase_k_and_no_spaces():
    """The client prints "₹1.5k"; this side used to print "₹1.5 K"."""
    import money_inr

    for value in (1_500, 12_34_567, 4_50_00_000):
        rendered = money_inr.inr_compact(value)
        assert " " not in rendered, rendered
    assert money_inr.inr_compact(1_500).endswith("k")
