"""Warm spare analyzers (Phase 2.3).

The win is ~540ms of measured ONNX rebuild moved out of every call's setup
window. The property that must never break is that two calls are never handed
the same object: both analyzers carry per-stream state, so sharing one would
have two concurrent callers analysing each other's audio.
"""

from __future__ import annotations

import threading

import pytest

from voice import analyzer_pool


class _Analyzer:
    """Stands in for an ONNX session: identity matters, construction is counted."""

    built = 0

    def __init__(self, tag: str = "default") -> None:
        type(self).built += 1
        self.tag = tag


@pytest.fixture(autouse=True)
def _clean():
    analyzer_pool.reset()
    _Analyzer.built = 0
    yield
    analyzer_pool.reset()


def _drain() -> None:
    """Wait for background refills to land."""
    analyzer_pool._BUILDERS.submit(lambda: None).result(timeout=10)


def test_two_calls_never_get_the_same_object():
    """The property the whole design exists to protect."""
    key = ("vad", 1.0)
    handed = [analyzer_pool.take(key, _Analyzer) for _ in range(6)]
    assert len({id(a) for a in handed}) == 6, "a spare was handed to two calls"


def test_a_warm_spare_is_used_instead_of_building_inline():
    key = ("vad", 1.0)
    analyzer_pool.seed(key, _Analyzer)
    _drain()
    assert analyzer_pool.stats()["spares"] == 1

    before = _Analyzer.built
    got = analyzer_pool.take(key, _Analyzer)
    # Taking the spare costs no build on the caller's thread.
    assert _Analyzer.built == before, "the call built its own despite a warm spare"
    assert got is not None
    _drain()
    # ...and the spare was replaced for the next call.
    assert analyzer_pool.stats()["spares"] == 1


def test_a_miss_builds_inline_exactly_as_before():
    got = analyzer_pool.take(("turn", 3.0), _Analyzer)
    assert isinstance(got, _Analyzer)
    assert _Analyzer.built == 1


def test_a_different_tuning_never_serves_the_wrong_spare():
    """The key is the cache's identity claim. A card with different VAD tuning
    must not inherit another card's analyzer."""
    analyzer_pool.seed(("vad", 0.7), lambda: _Analyzer("strict"))
    _drain()
    got = analyzer_pool.take(("vad", 0.9), lambda: _Analyzer("loose"))
    assert got.tag == "loose"


def test_the_pool_is_bounded():
    """Each spare is a live ONNX session held by nobody."""
    for i in range(analyzer_pool._MAX_KEYS + 4):
        analyzer_pool.seed(("vad", float(i)), _Analyzer)
    _drain()
    _drain()
    assert analyzer_pool.stats()["spares"] <= analyzer_pool._MAX_KEYS


def test_disabling_the_pool_restores_per_call_construction(monkeypatch):
    monkeypatch.setattr(analyzer_pool, "enabled", lambda: False)
    key = ("vad", 1.0)
    analyzer_pool.take(key, _Analyzer)
    analyzer_pool.take(key, _Analyzer)
    assert _Analyzer.built == 2
    assert analyzer_pool.stats() == {"spares": 0, "pending": 0}


def test_a_failing_build_does_not_wedge_the_key():
    """A spare that cannot be built must degrade to inline, not to nothing."""
    def boom():
        raise RuntimeError("onnx unavailable")

    analyzer_pool.seed(("vad", 1.0), boom)
    _drain()
    assert analyzer_pool.stats() == {"spares": 0, "pending": 0}
    # The key is still usable afterwards.
    got = analyzer_pool.take(("vad", 1.0), _Analyzer)
    assert isinstance(got, _Analyzer)


def test_concurrent_takes_are_each_served_once():
    key = ("vad", 1.0)
    analyzer_pool.seed(key, _Analyzer)
    _drain()

    out: list[object] = []
    lock = threading.Lock()

    def grab():
        got = analyzer_pool.take(key, _Analyzer)
        with lock:
            out.append(got)

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(out) == 8
    assert len({id(o) for o in out}) == 8, "the same spare went to two callers"


# ----------------------------------------------------- the keys are honest


def test_vad_key_covers_every_field_that_changes_behaviour():
    from pipecat.audio.vad.vad_analyzer import VADParams

    base = VADParams(confidence=0.7, start_secs=0.15, stop_secs=0.2, min_volume=0.6)
    key = analyzer_pool.vad_key(base)
    for field, value in (
        ("confidence", 0.8),
        ("start_secs", 0.3),
        ("stop_secs", 0.4),
        ("min_volume", 0.5),
    ):
        other = VADParams(
            **{**{
                "confidence": 0.7, "start_secs": 0.15,
                "stop_secs": 0.2, "min_volume": 0.6,
            }, field: value}
        )
        assert analyzer_pool.vad_key(other) != key, f"{field} is not in the key"


def test_turn_key_covers_every_field_that_changes_behaviour():
    from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams

    kw = {"stop_secs": 3.0, "pre_speech_ms": 0.0, "max_duration_secs": 8.0}
    key = analyzer_pool.turn_key(SmartTurnParams(**kw))
    for field, value in (
        ("stop_secs", 1.5),
        ("pre_speech_ms", 500.0),
        ("max_duration_secs", 12.0),
    ):
        other = SmartTurnParams(**{**kw, field: value})
        assert analyzer_pool.turn_key(other) != key, f"{field} is not in the key"
    assert analyzer_pool.turn_key(SmartTurnParams(**kw), cpu_count=2) != key
