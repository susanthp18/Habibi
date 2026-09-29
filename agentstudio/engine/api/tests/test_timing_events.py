"""Startup and per-reply timing reach the run's events as plain JSON."""

import json

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    MetricsFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.startup_timing_observer import StartupTimingObserver
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.processors.filters.identity_filter import IdentityFilter
from pipecat.tests.utils import run_test

from api.services.pipecat.run_pipeline import (
    latency_breakdown_payload,
    startup_timing_payload,
)


@pytest.mark.asyncio
async def test_timing_reports_become_run_events():
    startup, latency = StartupTimingObserver(), UserBotLatencyObserver()
    reports, breakdowns = [], []

    @startup.event_handler("on_startup_timing_report")
    async def on_report(_, report):
        reports.append(report)

    @latency.event_handler("on_latency_breakdown")
    async def on_breakdown(_, breakdown):
        breakdowns.append(breakdown)

    await run_test(
        IdentityFilter(),
        frames_to_send=[
            VADUserStoppedSpeakingFrame(),
            MetricsFrame(data=[TTFBMetricsData(processor="AzureLLMService#0", value=1.1)]),
            BotStartedSpeakingFrame(),
        ],
        expected_down_frames=[VADUserStoppedSpeakingFrame, MetricsFrame, BotStartedSpeakingFrame],
        observers=[startup, latency],
        # A cold process loads the deferred imports first (seconds).
        start_timeout=30,
    )

    started = json.loads(json.dumps(startup_timing_payload(reports[0])))
    assert started["total_seconds"] >= 0
    assert all({"processor", "seconds"} <= set(p) for p in started["slowest"])

    reply = json.loads(json.dumps(latency_breakdown_payload(breakdowns[0])))
    assert reply["measured_from"] == "user_silence"
    assert reply["parts"] and all({"label", "owner", "seconds"} <= set(p) for p in reply["parts"])
    assert abs(sum(p["seconds"] for p in reply["parts"]) - reply["total_seconds"]) < 0.01
