"""The answerability judge never ran, and the text worker was always cold.

Both were found by timing a real WhatsApp turn that took 59.7 seconds to answer
"what are the exclusions for travel insurance".

**The judge.** Every KB lookup logged "kb answerability degraded
(judge_unavailable) — passages unvetted", warm or cold, on both channels. The
budget was shared wall clock: subtracting a reserve from the *planner's*
timeout reserved nothing, because the embed and the vector search spend the
same deadline. Raising it to a real reserve was still not enough — the reserve
was passed straight through as the request timeout, and at 1.2s (then 2.5s) it
was smaller than the 2.10s-median / 2.41s-max call it was funding. The
resulting timeout was swallowed by a ``logger.debug``, so a compliance control
the system advertised had in fact never executed.

**The cold start.** ``bot_worker`` wakes only when a customer writes, so its
first Azure call of a turn paid full cold start every time: 11.2s for an intent
classification that runs 1.9s warm, 13.1s for a KB lookup that runs ~5s warm.
The voice runner has warmed its pool since it shipped; the text path never did.
"""

from __future__ import annotations

import inspect

import pytest

from agent_core.tools import kb_plan


# --- Deadline.guaranteed still behaves, and the judge is really gone --------


def test_the_floor_is_a_floor_not_a_remainder() -> None:
    """`Deadline.guaranteed` still owes its floor on an expired deadline.

    The judge it was built for is gone, but the mechanism is the generic one any
    future guaranteed-budget call would use, and its whole point is the case
    where nothing is left. Asserted against a literal rather than
    judge_reserve_s(), which no longer exists.
    """
    spent = kb_plan.Deadline(0.0)
    assert spent.remaining() == 0.0
    assert spent.guaranteed(2.5) == pytest.approx(2.5)


def test_the_floor_never_shrinks_a_healthy_budget() -> None:
    fresh = kb_plan.Deadline(30.0)
    assert fresh.guaranteed(1.0) > 25.0


def test_the_judge_is_not_called_at_all() -> None:
    """The judge is removed from the retrieval path, not just re-budgeted.

    It reserved a guaranteed 3.5s floor on every voice turn and failed open
    whenever the analysis lane saturated, so the cost was unconditional and the
    protection was not. Asserted against the source because the point is that
    the call site is gone -- a mock would pass just as happily with it present
    and disabled.
    """
    from agent_core.tools import kb

    src = inspect.getsource(kb)
    assert "judge_passages" not in src
    assert "judge_reserve_s" not in src
    assert "deadline.remaining(reserve=" not in src


@pytest.mark.parametrize("channel", ["voice", "text"])
def test_worst_case_retrieval_stays_within_the_dead_air_watchdog(channel: str) -> None:
    """Worst-case retrieval must not outlast the silence a caller will tolerate.

    Used to be budget + the judge's 3.5s floor, and the voice limit was 6.0s.
    Removing the judge removes the second term, so the same guard now holds
    against a much tighter limit — which is the point of keeping the test.
    """
    worst = kb_plan.budget_for(channel)
    limit = 2.5 if channel == "voice" else 4.0
    assert worst <= limit, f"{channel} worst-case retrieval {worst}s exceeds {limit}s"


# --- and a timeout must be visible ------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("read timed out"),
        type("APITimeoutError", (Exception,), {})("request timed out"),
    ],
)
def test_timeouts_are_recognised(exc: Exception) -> None:
    assert kb_plan._looks_like_timeout(exc)


def test_a_wrapped_timeout_is_recognised() -> None:
    """The SDK re-raises through its own class; the cause carries the truth."""
    inner = TimeoutError("read timed out")
    outer = RuntimeError("call failed")
    outer.__cause__ = inner
    assert kb_plan._looks_like_timeout(outer)


def test_other_failures_are_not_mislabelled_as_timeouts() -> None:
    assert not kb_plan._looks_like_timeout(ValueError("bad json"))
    assert not kb_plan._looks_like_timeout(KeyError("missing"))


def test_a_timeout_is_logged_loudly_enough_to_notice(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At logger.debug this hid a 100%-failing judge through two rounds of tuning."""
    import logging

    import azure_openai

    def _boom(*_a: object, **_k: object) -> None:
        raise TimeoutError("read timed out")

    monkeypatch.setattr(azure_openai, "chat_with_tools", _boom)
    with caplog.at_level(logging.WARNING, logger="agent_core.tools.kb_plan"):
        out = kb_plan._call_tool(
            system="s",
            user="u",
            tool={"type": "function", "function": {"name": "t"}},
            tool_name="t",
            max_tokens=64,
            budget=3.5,
        )
    assert out is None
    assert "timed out" in caplog.text
    assert "3.50s" in caplog.text


# --- the worker must not be cold when the customer writes -------------------


def test_prewarm_exists_and_is_bounded_by_an_idle_window() -> None:
    import azure_openai

    assert callable(azure_openai.prewarm)
    assert azure_openai.PREWARM_IDLE_SECONDS > 0


def test_prewarm_is_a_no_op_inside_the_idle_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The idle tick calls this every 1.5s; it must not dial Azure every time."""
    import azure_openai

    calls: list[int] = []

    class _Client:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**_k: object) -> None:
                    calls.append(1)

        class embeddings:  # noqa: N801
            @staticmethod
            def create(**_k: object) -> None:
                calls.append(1)

    monkeypatch.setattr(azure_openai, "get_client", lambda: _Client())
    monkeypatch.setattr(azure_openai, "get_chat_deployment", lambda: "gpt-test")
    monkeypatch.setattr(azure_openai, "get_embedding_deployment", lambda: "embed-test")
    monkeypatch.setattr(azure_openai, "_last_prewarm_at", 0.0)

    azure_openai.prewarm(force=True)
    first = len(calls)
    assert first >= 2, "chat and embeddings are separate deployments; warm both"

    azure_openai.prewarm()
    assert len(calls) == first, "second call inside the idle window must not dial"


def test_prewarm_failure_never_stops_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    import azure_openai

    def _boom() -> None:
        raise RuntimeError("azure down")

    monkeypatch.setattr(azure_openai, "get_client", _boom)
    assert azure_openai.prewarm(force=True) == 0.0


def test_the_worker_warms_at_start_and_while_idle() -> None:
    import bot_worker

    src = inspect.getsource(bot_worker.main)
    assert "azure_openai.prewarm(force=True)" in src, "warm before the first customer"
    assert src.count("prewarm") >= 2, "and keep it warm while idle"
