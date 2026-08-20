"""Latency helpers for the voice turn loop."""

from __future__ import annotations

from voice.llm_pool import (
    KeepAliveAzureLLMService as KeepAliveAzureLLMService,
    measure_bottlenecks as measure_bottlenecks,
    prewarm_shared_client,
)

# Back-compat alias used by bot/spike
prewarm_llm_connection = prewarm_shared_client
