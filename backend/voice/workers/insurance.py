"""Insurance specialist LLMWorker — RedisBus / local-bus mesh peer.

Run as a sidecar (docker compose ``voice_insurance`` or)::

    python -m voice.workers.insurance

Listens on the shared Pipecat bus. When collections activates ``insurance``
(on gated_upsell), this worker receives ``BusActivateWorkerMessage`` and can
answer product / eligibility turns via bridged LLM frames.

Until the main collections pipeline is fully BusBridge-based, activation is
also observed as a job-stream event for Floor / ops visibility.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("DB_PROCESS_ROLE", "voice")

from loguru import logger

from env_loader import load_env
from voice import config as voice_config


def _build_insurance_worker():
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.workers.llm import LLMWorker, LLMWorkerActivationArgs, tool

    from voice.latency import KeepAliveAzureLLMService
    from voice.tuning_apply import build_llm_settings_kwargs
    from agent_core import default_tuning

    tuning = default_tuning()
    llm = KeepAliveAzureLLMService(
        api_key=voice_config.azure_openai_voice_api_key(),
        endpoint=voice_config.azure_openai_voice_endpoint(),
        api_version=voice_config.azure_openai_voice_api_version(),
        settings=KeepAliveAzureLLMService.Settings(
            **build_llm_settings_kwargs(
                tuning,
                model=voice_config.azure_openai_voice_deployment(),
                system_instruction=(
                    "You are an HDFC insurance / upsell specialist. "
                    "Help with product eligibility and lead capture. "
                    "Keep replies to one or two short spoken sentences. "
                    "If the caller wants collections / PTP topics, call transfer_to_collections."
                ),
            )
        ),
    )

    class InsuranceWorker(LLMWorker):
        @tool(cancel_on_interruption=False)
        async def transfer_to_collections(
            self, params: FunctionCallParams, reason: str = "back_to_collections"
        ):
            """Hand the caller back to the collections agent."""
            await self.activate_worker(
                "collections",
                args=LLMWorkerActivationArgs(
                    messages=[{"role": "developer", "content": reason}],
                ),
                deactivate_self=True,
                result_callback=params.result_callback,
            )

        @tool
        async def check_product_eligibility(
            self, params: FunctionCallParams, product_id: str
        ):
            """Check whether the caller is eligible for a product."""
            from agent_core.tools import domain

            result = domain.check_product_eligibility(
                customer_id=os.getenv("MESH_CUSTOMER_ID") or "unknown",
                product_id=product_id,
            )
            await params.result_callback(result.data if result.ok else {"error": result.error})

        @tool
        async def capture_lead(
            self, params: FunctionCallParams, product_id: str, notes: str | None = None
        ):
            """Capture an upsell lead after consent."""
            from agent_core.tools import domain

            result = domain.capture_lead(
                customer_id=os.getenv("MESH_CUSTOMER_ID") or "unknown",
                product_id=product_id,
                source="voice_mesh",
                notes=notes,
            )
            await params.result_callback(result.data if result.ok else {"error": result.error})

    return InsuranceWorker("insurance", llm=llm, bridged=())


async def _make_bus():
    load_env()
    url = voice_config.redis_url()
    if not url:
        from pipecat.bus.local.async_queue import AsyncQueueBus

        logger.warning("REDIS_URL unset — insurance worker using in-process AsyncQueueBus")
        return AsyncQueueBus()
    from redis.asyncio import Redis
    from pipecat.bus.network.redis import RedisBus

    client = Redis.from_url(url, decode_responses=False)
    bus = RedisBus(redis=client, channel="bigbound.voice.mesh")
    await bus.start()
    logger.info("Insurance worker RedisBus ready · {}", url)
    return bus


async def main() -> None:
    load_env()
    from pipecat.workers.runner import WorkerRunner

    bus = await _make_bus()
    runner = WorkerRunner(name="insurance-runner", bus=bus, handle_sigint=True)
    worker = _build_insurance_worker()
    await runner.add_workers(worker)
    logger.info("Insurance LLMWorker registered — waiting for activate_worker('insurance')")
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
