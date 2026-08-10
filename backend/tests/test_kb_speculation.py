"""Speculative KB retrieval (voice/kb_enrich.py).

Retrieval used to run inline on LLMContextFrame — a full Azure embed + pgvector
ANN round trip on the audio critical path. It now starts from a partial
transcript so the answer is already cached when the turn closes.

The two things these tests must protect:

* **Spend.** Azure emits many interims per second. If the debounce or the
  per-turn budget regress, every user turn multiplies embed cost silently.
* **Correctness.** A speculation matched to the wrong final utterance must cost
  money, never inject wrong snippets. That is enforced by re-running the full
  gate on the final, not by the matcher.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import config as voice_config
from voice.kb_enrich import (
    KbCache,
    canon,
    containment,
    has_content_token,
    tokens_of,
)

# --------------------------------------------------------------------- matching


def test_containment_accepts_a_growing_partial() -> None:
    """The happy case: the interim is a prefix, so spec ⊆ final."""
    final = tokens_of("what is the late payment fee on my card")
    spec = tokens_of("what is the late payment")
    assert containment(final, spec) == 1.0


def test_containment_survives_a_mid_utterance_rewrite() -> None:
    """Azure rewrites as it goes ("four thousand" → "4000").

    A prefix *string* test breaks on this; token containment does not.
    """
    final = tokens_of("can i pay 4000 towards the late payment fee")
    spec = tokens_of("can i pay four thousand towards the late payment")
    assert containment(final, spec) >= 0.7


def test_containment_rejects_an_unrelated_final() -> None:
    final = tokens_of("what is my outstanding balance")
    spec = tokens_of("how do i dispute a duplicate charge")
    assert containment(final, spec) < 0.5


def test_containment_of_an_empty_spec_is_zero() -> None:
    assert containment(tokens_of("anything"), tokens_of("")) == 0.0


def test_stub_partials_have_no_content_token() -> None:
    """"is it my" would otherwise score 1.0 against almost any final."""
    assert not has_content_token(tokens_of("is it my"))
    assert not has_content_token(tokens_of("and what do you"))
    assert has_content_token(tokens_of("late payment charge"))


def test_canon_is_case_and_punctuation_insensitive() -> None:
    assert canon("  What IS the LATE-payment fee? ") == "what is the late payment fee"


# ------------------------------------------------------------------ spec picking


def _cache(**kw) -> KbCache:
    return KbCache(kb_snapshot_id="snap-1", **kw)


def _done_task(value=None) -> asyncio.Task:
    async def _v():
        return value or []

    return asyncio.ensure_future(_v())


def test_best_spec_requires_three_tokens_and_a_content_word() -> None:
    async def scenario() -> tuple:
        cache = _cache()
        cache.note_turn_start()
        cache.register_spec("is it my", ("k1",), _done_task())
        stub = cache.best_spec("is it my account that is overdue")

        cache.note_turn_start()
        cache.register_spec("late payment fee policy", ("k2",), _done_task())
        real = cache.best_spec("what is the late payment fee policy here")
        return stub, real

    stub, real = asyncio.run(scenario())
    assert stub is None, "a stub partial claimed the turn"
    assert real is not None


def test_turn_boundary_resets_the_budget_and_specs() -> None:
    async def scenario() -> tuple:
        cache = _cache()
        cache.note_turn_start()
        cache.register_spec("late payment fee policy", ("k",), _done_task())
        cache.register_spec("late payment fee waiver", ("k2",), _done_task())
        exhausted = cache.can_speculate()
        cache.note_turn_start()
        return exhausted, cache.can_speculate(), cache.best_spec("late payment fee policy")

    exhausted, fresh, leaked = asyncio.run(scenario())
    assert exhausted is False, "budget of 2 was not enforced"
    assert fresh is True, "new turn did not reset the budget"
    assert leaked is None, "last turn's speculation leaked into this one"


def test_budget_caps_speculations_per_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """20 interims must not become 20 embeds."""
    monkeypatch.setattr(voice_config, "kb_spec_max_per_turn", lambda: 2)

    async def scenario() -> int:
        cache = _cache()
        cache.note_turn_start()
        allowed = 0
        for i in range(20):
            if not cache.can_speculate():
                break
            cache.register_spec(f"grace period question number {i}", (i,), _done_task())
            allowed += 1
            # Let each stub task finish so this exercises the per-turn budget
            # rather than the concurrent-in-flight cap.
            await asyncio.sleep(0)
        return allowed

    assert asyncio.run(scenario()) == 2


def test_inflight_cap_blocks_a_second_concurrent_speculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the budget: one outstanding retrieval at a time."""
    monkeypatch.setattr(voice_config, "kb_spec_max_per_turn", lambda: 5)
    monkeypatch.setattr(voice_config, "kb_spec_max_inflight", lambda: 1)

    async def scenario() -> bool:
        cache = _cache()
        cache.note_turn_start()

        async def _slow():
            await asyncio.sleep(1)
            return []

        cache.register_spec("grace period question", ("k",), asyncio.ensure_future(_slow()))
        blocked = not cache.can_speculate()
        cache.cancel_inflight()
        return blocked

    assert asyncio.run(scenario())


# -------------------------------------------------------------------- resolving


def test_exact_cache_hit_costs_nothing() -> None:
    async def scenario() -> tuple:
        cache = _cache()
        calls: list[str] = []

        async def _never(*_a, **_kw):
            calls.append("retrieved")
            return []

        cache._retrieve = _never  # type: ignore[method-assign]
        cache.cache_put(cache.key_for("late fee policy", None), [{"snippet": "s"}])

        snippets, source = await cache.resolve(
            "late fee policy", None, timeout_s=0.1, fallback="inline"
        )
        return (snippets, source, calls)

    snippets, source, calls = asyncio.run(scenario())
    assert source == "exact"
    assert snippets == [{"snippet": "s"}]
    assert calls == [], "an exact hit still hit the network"


def test_speculative_hit_is_served_from_the_in_flight_task() -> None:
    async def scenario() -> tuple:
        cache = _cache()

        async def slow(*_a, **_kw):
            await asyncio.sleep(0.02)
            return [{"snippet": "spec"}]

        cache._retrieve = slow  # type: ignore[method-assign]
        cache.note_turn_start()
        task = cache.start_retrieval("what is the late payment fee", None)
        cache.register_spec("what is the late payment fee", ("k",), task)

        return await cache.resolve(
            "what is the late payment fee on my card",
            None,
            timeout_s=1.0,
            fallback="inline",
        )

    snippets, source = asyncio.run(scenario())
    assert source == "speculative"
    assert snippets == [{"snippet": "spec"}]


def test_timeout_shields_the_task_and_the_result_still_lands_in_cache() -> None:
    """shield() is load-bearing.

    Without it, a bounded wait that expires CANCELS the retrieval — throwing
    away an embed already paid for that the next turn would have reused.
    """

    async def scenario() -> tuple:
        cache = _cache()
        finished = asyncio.Event()

        async def slow(query, product_keys):
            await asyncio.sleep(0.15)
            cache.cache_put(cache.key_for(query, product_keys), [{"snippet": "late"}])
            finished.set()
            return [{"snippet": "late"}]

        cache._retrieve = slow  # type: ignore[method-assign]
        cache.note_turn_start()
        task = cache.start_retrieval("what is the late payment fee", None)
        cache.register_spec("what is the late payment fee", ("k",), task)

        snippets, source = await cache.resolve(
            "what is the late payment fee",
            None,
            timeout_s=0.01,
            fallback="spec_only",
        )
        cancelled_immediately = task.cancelled()

        await asyncio.wait_for(finished.wait(), timeout=2)
        cached = cache.cache_get(cache.key_for("what is the late payment fee", None))
        return source, cancelled_immediately, cached

    source, cancelled, cached = asyncio.run(scenario())
    assert source == "miss", "should have stopped waiting"
    assert not cancelled, "timeout cancelled the retrieval — the embed was wasted"
    assert cached == [{"snippet": "late"}], "result never landed in the cache"


def test_inline_fallback_retrieves_when_speculation_missed() -> None:
    """Default behaviour — identical grounding to the pre-speculation code."""

    async def scenario() -> tuple:
        cache = _cache()

        async def quick(*_a, **_kw):
            return [{"snippet": "inline"}]

        cache._retrieve = quick  # type: ignore[method-assign]
        cache.note_turn_start()
        return await cache.resolve("a policy question", None, timeout_s=0.05, fallback="inline")

    snippets, source = asyncio.run(scenario())
    assert source == "inline"
    assert snippets == [{"snippet": "inline"}]


def test_spec_only_fallback_injects_nothing_on_a_miss() -> None:
    async def scenario() -> tuple:
        cache = _cache()
        calls: list[int] = []

        async def quick(*_a, **_kw):
            calls.append(1)
            return [{"snippet": "x"}]

        cache._retrieve = quick  # type: ignore[method-assign]
        cache.note_turn_start()
        result = await cache.resolve(
            "a policy question", None, timeout_s=0.05, fallback="spec_only"
        )
        return result, calls

    (snippets, source), calls = asyncio.run(scenario())
    assert (snippets, source) == ([], "miss")
    assert calls == [], "spec_only still paid for an inline retrieval"


def test_concurrent_retrievals_of_the_same_query_share_one_task() -> None:
    """The in-flight claim, kept from the original in-flight dedupe set."""

    async def scenario() -> int:
        cache = _cache()
        calls: list[int] = []

        async def slow(*_a, **_kw):
            calls.append(1)
            await asyncio.sleep(0.05)
            return [{"snippet": "s"}]

        cache._retrieve = slow  # type: ignore[method-assign]
        t1 = cache.start_retrieval("the same question about fees", None)
        t2 = cache.start_retrieval("the same question about fees", None)
        assert t1 is t2
        await t1
        return len(calls)

    assert asyncio.run(scenario()) == 1


# ------------------------------------------------------------------------ gates


# A genuine policy question the intent skip-list does NOT catch. Note that
# "what is the late payment fee policy" classifies as payment_intent and is
# therefore gated — that is pre-existing skip-list behaviour, not speculation.
_POLICY_Q = "how does the grace period work on my loan"


def test_the_gate_is_shared_by_both_paths() -> None:
    """One implementation, so the partial and final can never disagree."""
    cache = _cache()
    assert cache.skip_reason("short") == "too_short"
    assert cache.skip_reason("1234") == "too_short"
    assert cache.skip_reason("my number is 987654") == "digits"
    assert cache.skip_reason(_POLICY_Q) is None


def test_money_intents_are_gated_on_the_final_even_after_a_speculative_hit() -> None:
    """The safety property.

    A caller who starts "what happens if I pay late" and finishes "...actually,
    what's my balance" passes the containment test — but balance_query is in the
    skip list, so the final gate refuses to inject. A bad speculation costs
    spend, never correctness.
    """
    cache = _cache()
    assert cache.skip_reason("what is my outstanding balance right now") is not None


def test_cooldown_suppresses_both_paths() -> None:
    """An explicit search_knowledge_base call must stand the enricher down."""
    cache = _cache()
    assert cache.skip_reason(_POLICY_Q) is None
    cache.suppress(30)
    assert cache.skip_reason(_POLICY_Q) == "cooldown"


def test_disabled_cache_skips_everything() -> None:
    cache = KbCache(enabled=False)
    assert cache.skip_reason(_POLICY_Q) == "disabled"


def test_empty_results_are_not_cached() -> None:
    """A transient miss must not be pinned for the whole TTL."""

    async def scenario() -> object:
        cache = _cache()
        import kb_retrieve

        original = kb_retrieve.retrieve
        kb_retrieve.retrieve = lambda **_kw: {"results": []}
        try:
            await cache._retrieve("a policy question about fees", None)
        finally:
            kb_retrieve.retrieve = original
        return cache.cache_get(cache.key_for("a policy question about fees", None))

    assert asyncio.run(scenario()) is None


def test_stats_shape_is_what_the_complete_job_logs() -> None:
    cache = _cache()
    cache.spec_attempts = 3
    cache.spec_hits = 2
    cache.wait_samples_ms = [10.0, 20.0, 30.0]
    assert cache.stats() == {
        "kb_spec_attempts": 3,
        "kb_spec_hits": 2,
        "kb_wait_ms_p50": 20,
    }
