"""Latency helpers for the voice turn loop."""

from __future__ import annotations

from voice.llm_pool import (  # noqa: F401 — re-export
    KeepAliveAzureLLMService,
    get_shared_client,
    measure_bottlenecks,
    prewarm_shared_client,
)

# Back-compat aliases used by bot/spike
prewarm_llm_connection = prewarm_shared_client

# Back-compat — prefer with_voice_naturalness (tone + brevity).
from voice.natural import VOICE_NATURALNESS_OVERLAY, with_voice_naturalness

VOICE_BREVITY_OVERLAY = VOICE_NATURALNESS_OVERLAY


def with_voice_brevity(system_instruction: str) -> str:
    return with_voice_naturalness(system_instruction)


# Deprecated: prefer get_shared_client() so prewarm and Pipecat share sockets.
def make_async_openai_client():
    from voice.llm_pool import get_shared_client_sync

    return get_shared_client_sync()
