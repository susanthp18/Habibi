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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.workers.llm import LLMWorker, LLMWorkerActivationArgs, tool

from env_loader import load_env
from voice import config as voice_config


def _build_insurance_worker():
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
        def _activation_args(self, params: FunctionCallParams) -> dict:
            args = getattr(params, "activation_args", None) or getattr(
                self, "activation_args", None
            )
            return args if isinstance(args, dict) else {}

        def _customer_id(self, params: FunctionCallParams) -> str | None:
            args = self._activation_args(params)
            cid = (args.get("customerId") or args.get("customer_id") or "").strip()
            if cid and cid.lower() != "unknown":
                return cid
            # Fallback: bus / env may carry the bound caller for mesh demos.
            cid = (os.getenv("MESH_CUSTOMER_ID") or "").strip()
            if cid and cid.lower() != "unknown":
                return cid
            return None

        def _interaction_id(self, params: FunctionCallParams) -> str | None:
            """The call this specialist is answering on.

            Without it every mesh-captured lead landed with no source call, no
            lead_captured interaction event and no upsell_presented flag — a
            lead in the pipeline that no call could be traced to.
            """
            args = self._activation_args(params)
            ix = (args.get("interactionId") or args.get("interaction_id") or "").strip()
            return ix or None

        def _bot_id(self, params: FunctionCallParams) -> str | None:
            args = self._activation_args(params)
            return (args.get("botId") or args.get("bot_id") or "").strip() or None

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
        async def recommend_next_offer(self, params: FunctionCallParams):
            """Ask the offer engine what may be mentioned to this caller."""
            cid = self._customer_id(params)
            if not cid:
                await params.result_callback({"error": "customer_unbound"})
                return
            try:
                from agent_core.reco import engine as reco_engine

                result = await asyncio.to_thread(
                    reco_engine.recommend,
                    customer_id=cid,
                    interaction_id=self._interaction_id(params),
                    channel="voice",
                )
            except Exception as exc:
                logger.exception("mesh recommend_next_offer failed")
                await params.result_callback(
                    {"offers": [], "suppressed": True, "suppressionReason": str(exc)[:200]}
                )
                return
            await params.result_callback(result.to_tool_payload())

        @tool
        async def check_product_eligibility(
            self, params: FunctionCallParams, product_id: str
        ):
            """Check whether the caller is eligible for a product."""
            from agent_core.tools import domain

            cid = self._customer_id(params)
            if not cid:
                await params.result_callback({"error": "customer_unbound"})
                return
            result = await asyncio.to_thread(
                domain.check_product_eligibility,
                customer_id=cid,
                product_id=product_id,
                interaction_id=self._interaction_id(params),
                bot_id=self._bot_id(params),
                channel="voice",
            )
            await params.result_callback(result.data if result.ok else {"error": result.error})

        @tool
        async def capture_lead(
            self, params: FunctionCallParams, product_id: str, summary: str | None = None
        ):
            """Capture an upsell lead after consent."""
            from agent_core.tools import domain

            cid = self._customer_id(params)
            if not cid:
                await params.result_callback({"error": "customer_unbound"})
                return
            interaction_id = self._interaction_id(params)
            # Blocking DB work off the event loop, and `summary` — not `notes`,
            # which is not a parameter of capture_lead and raised TypeError
            # inside the tool, so the result callback never fired and the turn
            # hung with no reply.
            result = await asyncio.to_thread(
                domain.capture_lead,
                customer_id=cid,
                product_id=product_id,
                interaction_id=interaction_id,
                bot_id=self._bot_id(params),
                summary=summary,
                source="voice_mesh",
                channel="voice",
                idempotency_key=f"mesh-lead:{interaction_id or 'no-ix'}:{cid}:{product_id}",
            )
            await params.result_callback(result.data if result.ok else {"error": result.error})

    return InsuranceWorker("insurance", llm=llm, bridged=())


def _make_bus():
    """Build bus only — WorkerRunner.setup/start wires TaskManager."""
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
    # REDIS_URL commonly carries redis://user:password@host — never log it raw.
    logger.info("Insurance worker RedisBus configured · {}", _redact_redis_url(url))
    return bus


def _redact_redis_url(url: str) -> str:
    """host:port only — drops any userinfo credentials from the URL."""
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
        host = parts.hostname or "?"
        return f"{parts.scheme}://{host}:{parts.port}" if parts.port else f"{parts.scheme}://{host}"
    except ValueError:
        return "<redacted>"


async def main() -> None:
    load_env()
    from pipecat.workers.runner import WorkerRunner

    bus = _make_bus()
    # auto_end=False: LLMWorker waits forever for BusActivateWorkerMessage.
    runner = WorkerRunner(name="insurance-runner", bus=bus, handle_sigint=True)
    worker = _build_insurance_worker()
    await runner.add_workers(worker)
    logger.info("Insurance LLMWorker registered — waiting for activate_worker('insurance')")
    await runner.run(auto_end=False)


if __name__ == "__main__":
    asyncio.run(main())
