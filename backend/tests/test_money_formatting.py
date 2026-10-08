"""One money format across the server/client seam.

The AssignedQueue row is the reason this file exists. Its amount column is
rendered by the client with ``Intl.NumberFormat("vi-VN", {style: "currency",
currency: "VND"})``; its detail column is a *string the server already baked*
("Promised …", "Disputed …"). Those two cells sit one column apart on the same
row, so any disagreement between Python's formatting and ICU's is visible
without scrolling — and Python's ``f"{x:,}"`` knows neither the vi-VN dot
grouping nor where the symbol goes.

The ``expected`` strings below are not hand-derived. They are the literal
output of the client's ``fmtMoney`` / ``inrCompact`` in node, which is the same
ICU data the browser uses, so a passing test here is a statement about the two
renderings agreeing rather than about one implementation's opinion. ``_`` in a
table stands for the no-break space ICU puts before the symbol and the
compact suffix.
"""

from __future__ import annotations

import pytest

import db


def v(text: str) -> str:
    """A table string with ``_`` for the no-break space ICU prints."""
    return text.replace("_", " ")


# (value, exactly what the client prints for the same value)
GROUPING_CASES = [
    (0, v("0_₫")),
    (999, v("999_₫")),
    (1_000, v("1.000_₫")),
    (9_999, v("9.999_₫")),
    (100_000, v("100.000_₫")),
    (999_999, v("999.999_₫")),
    (1_000_000, v("1.000.000_₫")),
    (1_234_567, v("1.234.567_₫")),
    (10_000_000, v("10.000.000_₫")),
    (-999, v("-999_₫")),
    (-1_234_567, v("-1.234.567_₫")),
]


@pytest.mark.parametrize("value, expected", GROUPING_CASES)
def test_inr_groups_the_vietnamese_way(value, expected):
    """Dot grouping and a trailing symbol at every boundary that changes shape."""
    assert db._inr(value) == expected


def test_inr_keeps_the_em_dash_for_a_missing_amount():
    """Not every work item has an amount; "—" is the column's empty state."""
    assert db._inr(None) == "—"


def test_inr_rounds_to_whole_dong():
    """The detail column is prose, not a ledger."""
    assert db._inr(1_234_567.4) == v("1.234.567_₫")
    assert db._inr(99_999.6) == v("100.000_₫")


def test_inr_does_not_render_negative_zero():
    """A balance that rounds away to nothing is "0 ₫", never "-0 ₫"."""
    assert db._inr(-0.4) == v("0_₫")


def test_inr_puts_the_sign_before_the_number():
    """Matches the client's ``fmtMoney(-500)`` → "-500 ₫". Overpaid accounts
    make this reachable."""
    assert db._inr(-500) == v("-500_₫")


def test_work_item_detail_strings_group_the_same_way_as_the_amount_column():
    """The original defect, at the level the user actually sees it.

    Both halves of the row are built here from one value: the detail string the
    server ships, and the client's rendering of the amount alongside it.
    """
    amount = 1_234_567.0
    client_amount_cell = v("1.234.567_₫")  # node: fmtMoney(1234567)

    assert f"Promised {db._inr(amount)}" == f"Promised {client_amount_cell}"
    assert f"Disputed {db._inr(amount)}" == f"Disputed {client_amount_cell}"
    assert (
        f"Paid {db._inr(200_000.0)} of {db._inr(amount)} promised"
        == f"Paid {v('200.000_₫')} of {client_amount_cell} promised"
    )


# ---------------------------------------------------------------------------
# The shared module, and the call sites that used to disagree with it.
#
# Six modules carried their own _inr, and two of them feed text a customer
# hears: the agent's system prompt (agent_core/context.py) and the
# goodwill-waiver line it speaks (agent_core/authority/talk.py). money_inr is
# the single implementation they all now delegate to; these assert each seam
# separately, because a shared helper that one caller has quietly stopped using
# is not shared.
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
    # Standard library only: __future__ and decimal (the quantizer).
    assert [m for m in imported if m not in {"__future__", "decimal"}] == []


def test_the_null_reading_is_per_call_site():
    """A table cell wants an em dash; a spoken sentence wants nothing."""
    import money_inr

    assert money_inr.inr(None) == "—"
    assert money_inr.inr(None, none="") == ""


def test_the_agent_prompt_card_uses_the_shared_format():
    """This string goes into the model's system prompt and gets spoken."""
    from agent_core import context

    assert context._inr(1_234_567) == v("1.234.567_₫")
    # Unusable values are dropped from the card rather than rendered as a dash.
    assert context._inr(None) is None
    assert context._inr("not a number") is None


def test_the_goodwill_talk_track_uses_the_shared_format():
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
    assert v("1.234.567_₫") in line
    assert "1,234,567" not in line


def test_the_customer_insight_label_uses_the_shared_format():
    """Also the site of a no-op ``.replace(",", ",")`` that did nothing."""
    import customer_insights

    assert customer_insights._inr(1_234_567) == v("1.234.567_₫")


def test_the_offer_insight_label_uses_the_shared_formatter():
    import customer_insights

    nba = customer_insights._offer_nba(
        {"status": "ready", "productName": "Top-up loan", "suggestedAmount": 1_234_567}
    )
    assert nba is not None
    assert v("1.234.567_₫") in nba["title"]


def test_the_treatment_narration_carries_one_money_format():
    """The decision log's explanation of why an action was taken.

    It used to print two money formats inside a single sentence.
    """
    from agent_core.treatment import narrate

    assert narrate._inr(1_234_567) == v("1.234.567_₫")


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
    assert v("1.234.567_₫") in line
    assert v("4,50_₫") in line
    assert "1,234,567" not in line


# ---------------------------------------------------------------------------
# The compact ladder. This table is mirrored byte-for-byte in
# Habibi/src/lib/format.test.ts — change one, change both.
# ---------------------------------------------------------------------------

COMPACT_CASES = [
    (0, v("0_₫")),
    (0.00004, v("<0,0001_₫")),
    (0.0001, v("0,0001_₫")),
    (0.004, v("0,0040_₫")),
    (0.9999, v("0,9999_₫")),
    (1, v("1,00_₫")),
    (12.5, v("12,50_₫")),
    (999.99, v("999,99_₫")),
    (1_000, v("1_N_₫")),
    (1_500, v("1,5_N_₫")),
    (99_999, v("100_N_₫")),
    (100_000, v("100_N_₫")),
    (1_234_567, v("1,2_Tr_₫")),
    (9_999_999, v("10_Tr_₫")),
    (10_000_000, v("10_Tr_₫")),
    (45_000_000, v("45_Tr_₫")),
    (4_500_000_000, v("4,5_T_₫")),
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
    """main.py says a metering gap must not be shown as a genuine zero.

    The old ladder formatted everything under 1000 as a whole number, so a call
    that really cost 0.004 of LLM tokens rendered as "0" — the same string as a
    call that was never metered at all.
    """
    import money_inr

    assert money_inr.inr_compact(tiny) == v("<0,0001_₫")
    assert money_inr.inr_compact(tiny) != v("0_₫")


def test_inr_compact_promotes_a_suffix_that_rounds_up_to_a_thousand():
    """999,96 N rounds to 1000,0 N; ICU prints it as "1 Tr", and so must we."""
    import money_inr

    assert money_inr.inr_compact(999_940) == v("999,9_N_₫")
    assert money_inr.inr_compact(999_960) == v("1_Tr_₫")


def test_spoken_money_follows_the_account_currency():
    from money_inr import spoken_money

    assert spoken_money(1_250_000, "INR") == "₹12,50,000"
    assert spoken_money(12_500, "AED") == "AED 12,500"
    assert spoken_money(12_500, "VND") == "VND 12,500"
    # No account currency: the deployment's.
    assert spoken_money(12_500.4, None) == "VND 12,500"
    assert spoken_money(None, "AED") is None
