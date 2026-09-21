"""One trace line per turn, in the caller's clock.

Carved out of :mod:`voice.crm_sink` for the reason its docstring already gives
for :mod:`voice.crm_sink_observer`: the sink is the queue and its writers.
Assembling a measurement from six producers is neither.

The clock
---------
The origin is already correct in Pipecat 1.6.0 and was widely assumed not to
be. ``UserBotLatencyObserver`` stamps::

    self._user_stopped_time = data.frame.timestamp - data.frame.stop_secs

-- the caller's true speech end, VAD hang subtracted -- and measures
``on_latency_measured`` from it. What it does *not* include is the tail:
``BotStartedSpeakingFrame`` fires when the first audio is handed to the
transport, not when it reaches the handset, so the output buffer has to be
added back before the number is what the borrower felt. Both are reported, so
the two can be compared rather than confused.

What it collects
----------------
Almost nothing here is newly measured. These values were already being
computed and then dropped on the floor:

===========================  ==========================================
Smart Turn inference + verdict  ``TurnMetricsData``, ignored by the observer
KB source and wait              returned by ``KbCache.resolve``, discarded
TTS leading silence             read, then logged at DEBUG
per-service TTFB, tool, agg     mapped for a DB column, never traced
===========================  ==========================================

Isolation
---------
Every line carries the cell it belongs to -- transport, sample rate, output
buffer depth, concurrency at setup. Pooling 8 kHz and 16 kHz, or cold and
warm, into one p50 is what makes a latency number meaningless: at 8 kHz Smart
Turn additionally resamples an 8-second window on every turn end, so the two
are not the same measurement and must never share a percentile.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TurnTrace:
    """Per-call collector for one ``turn.e2e`` line per turn."""

    __slots__ = ("_trace", "_context", "_extra")

    def __init__(self, trace: Callable[..., None]) -> None:
        #: The sink's ``_trace``, so every line carries the ids that join it
        #: back to the dial.
        self._trace = trace
        self._context: dict[str, Any] = {}
        self._extra: dict[str, Any] = {}

    @property
    def pending(self) -> dict[str, Any]:
        """This turn's values so far. Read-only by convention; do not clear."""
        return self._extra

    def set_context(self, **fields: Any) -> None:
        """Stamp the per-call facts every turn is compared within."""
        self._context.update({k: v for k, v in fields.items() if v is not None})

    def record(self, **fields: Any) -> None:
        """Collect one turn's values from whichever producer computed them."""
        for key, value in fields.items():
            if value is not None:
                self._extra[key] = value

    def clear(self) -> None:
        """Drop this turn's values.

        Called at turn start as well as after emitting: ``emit`` only runs on
        ``BotStartedSpeakingFrame``, so a turn the bot never answers would
        otherwise carry its measurements into the next one and report them
        there. A per-turn value that outlives its turn describes the wrong turn.
        """
        self._extra = {}

    def emit(
        self,
        breakdown: Any,
        *,
        latency_ms: float | None = None,
        stages: dict[str, Any] | None = None,
    ) -> None:
        """Emit the line and clear the turn."""
        try:
            fields = dict(self._context)
            fields.update(stages or {})
            fields.update(self._extra)
            self.clear()

            out_buffer_ms = float(self._context.get("out_buffer_ms") or 0.0)
            if latency_ms and latency_ms > 0:
                fields["pipeline_ms"] = int(latency_ms)
                fields["caller_ms"] = int(latency_ms + out_buffer_ms)

            turn_start = getattr(breakdown, "user_turn_start_time", None)
            fields["origin"] = "speech_end" if turn_start else "unknown"
            self._trace("turn.e2e", **fields)
        except Exception:
            logger.debug("turn.e2e trace failed", exc_info=True)
