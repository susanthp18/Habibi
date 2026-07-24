"""
V0 latency spike — SmallWebRTC + Azure STT/LLM/TTS, no CRM, no DB.

Run from backend/:
  .\\.venv\\Scripts\\python.exe -m voice.spike

Opens the Pipecat prebuilt UI at http://localhost:7860 (WebRTC).
enable_metrics=True — watch loguru for TTFB / TTFA per service.

Non-interactive LLM TTFB probe (no mic):
  .\\.venv\\Scripts\\python.exe -m voice.spike --probe-ttfb --rounds 5

Bottleneck breakdown (DNS / cold HTTP / warm HTTP / LLM TTFB):
  .\\.venv\\Scripts\\python.exe -m voice.spike --bottlenecks

Env mapping (ours → Pipecat constructors, explicit — do not rename globals):
  AZURE_SPEECH_KEY          → api_key (STT/TTS)
  AZURE_SPEECH_REGION       → region
  AZURE_OPENAI_API_KEY      → api_key (LLM)
  AZURE_OPENAI_ENDPOINT     → endpoint
  AZURE_OPENAI_VOICE_DEPLOYMENT || AZURE_OPENAI_CHAT_DEPLOYMENT → model
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

# Ensure backend/ is on path when run as a script.
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from loguru import logger

from voice import config as voice_config
from voice.latency import KeepAliveAzureLLMService, measure_bottlenecks, prewarm_llm_connection
from voice.llm_pool import get_shared_client


async def probe_llm_ttfb(*, rounds: int = 5) -> None:
    """Measure first-token latency against the shared keep-alive voice client."""
    client = await get_shared_client()
    await prewarm_llm_connection(force=True)
    deployment = voice_config.azure_openai_voice_deployment()
    chat_fallback = voice_config.azure_openai_chat_deployment()
    logger.info(
        "TTFB probe · voice_deployment={} · endpoint={} · chat_fallback={} · rounds={} · shared_keepalive=yes",
        deployment,
        voice_config.azure_openai_voice_endpoint(),
        chat_fallback,
        rounds,
    )

    samples_ms: list[float] = []
    prompt = (
        "You are a voice assistant. Respond in 1 brief sentence. "
        "Never use lists, markdown, or emojis."
    )
    user = "Hi, can I pay my EMI next Friday?"

    for i in range(rounds):
        t0 = time.perf_counter()
        first_token_at: float | None = None
        chunks = 0
        try:
            stream = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=64,
                stream=True,
            )
        except Exception:
            stream = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_completion_tokens=64,
                stream=True,
            )
        async for event in stream:
            chunks += 1
            delta = ""
            if event.choices:
                delta = event.choices[0].delta.content or ""
            if delta and first_token_at is None:
                first_token_at = time.perf_counter()
                break
        try:
            async for _ in stream:
                pass
        except Exception:
            pass

        if first_token_at is None:
            logger.warning("round {} · no token received", i + 1)
            continue
        ttfb_ms = (first_token_at - t0) * 1000.0
        samples_ms.append(ttfb_ms)
        logger.info("round {} · TTFB={:.0f} ms · chunks_seen={}", i + 1, ttfb_ms, chunks)

    if not samples_ms:
        logger.error("No TTFB samples — check Azure OpenAI credentials / deployment")
        return

    samples_ms.sort()
    p50 = statistics.median(samples_ms)
    p95_idx = min(len(samples_ms) - 1, max(0, int(round(0.95 * (len(samples_ms) - 1)))))
    p95 = samples_ms[p95_idx]
    mean = statistics.mean(samples_ms)
    logger.info(
        "TTFB summary · n={} · mean={:.0f} ms · p50={:.0f} ms · p95={:.0f} ms · "
        "exit_criterion p50<1000ms → {}",
        len(samples_ms),
        mean,
        p50,
        p95,
        "PASS" if p50 < 1000 else "FAIL — network/model floor (see --bottlenecks)",
    )


async def run_bot(transport, runner_args) -> None:
    """Throwaway cascaded STT→LLM→TTS pipeline with metrics."""
    from pipecat.audio.vad.silero import SileroVADAnalyzer
    from pipecat.frames.frames import LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.azure.stt import AzureSTTService
    from pipecat.services.azure.tts import AzureTTSService
    from pipecat.transcriptions.language import Language
    from pipecat.services.tts_service import TextAggregationMode
    from pipecat.workers.runner import WorkerRunner

    speech_key = voice_config.azure_speech_key()
    speech_region = voice_config.azure_speech_region()
    voice_name = voice_config.azure_speech_default_voice()
    deployment = voice_config.azure_openai_voice_deployment()

    logger.info(
        "Spike bot · stt/tts region={} · voice={} · llm_deployment={} · shared_keepalive=yes",
        speech_region,
        voice_name,
        deployment,
    )

    stt = AzureSTTService(
        api_key=speech_key,
        region=speech_region,
        settings=AzureSTTService.Settings(language=Language.EN_IN),
    )
    tts = AzureTTSService(
        api_key=speech_key,
        region=speech_region,
        settings=AzureTTSService.Settings(voice=voice_name),
        text_aggregation_mode=TextAggregationMode.SENTENCE,
    )
    llm = KeepAliveAzureLLMService(
        api_key=voice_config.azure_openai_voice_api_key(),
        endpoint=voice_config.azure_openai_voice_endpoint(),
        api_version=voice_config.azure_openai_voice_api_version(),
        settings=KeepAliveAzureLLMService.Settings(
            model=deployment,
            temperature=0.2,
            system_instruction=(
                "You are a voice assistant. Respond in 1 brief sentence. "
                "Never use lists, markdown, or emojis."
            ),
        ),
    )
    asyncio.create_task(prewarm_llm_connection())

    context = LLMContext()
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected — kicking off greeting")
        context.add_message(
            {
                "role": "developer",
                "content": "Greet the caller briefly as Priya from HDFC collections.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)
    await runner.run()


async def bot(runner_args):
    from pipecat.evals.transport import EvalTransportParams
    from pipecat.runner.utils import create_transport
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    transport_params = {
        "eval": lambda: EvalTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "twilio": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    }
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def _ensure_utf8_stdio() -> None:
    """Pipecat's runner banner uses box-drawing chars; Windows cp1252 blows up."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice agent V0 spike")
    parser.add_argument(
        "--probe-ttfb",
        action="store_true",
        help="Measure LLM first-token latency without starting WebRTC",
    )
    parser.add_argument(
        "--bottlenecks",
        action="store_true",
        help="Break down DNS / cold HTTP / warm HTTP / LLM TTFB",
    )
    parser.add_argument("--rounds", type=int, default=5, help="TTFB / bottleneck LLM rounds")
    # Pipecat runner also parses argv; strip our flags before handing off.
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]

    if args.bottlenecks:
        report = asyncio.run(measure_bottlenecks(rounds=max(1, args.rounds)))
        import json

        print(json.dumps(report, indent=2))
        return

    if args.probe_ttfb:
        asyncio.run(probe_llm_ttfb(rounds=max(1, args.rounds)))
        return

    _ensure_utf8_stdio()
    from pipecat.runner.run import main as pipecat_main

    pipecat_main()


if __name__ == "__main__":
    main()
