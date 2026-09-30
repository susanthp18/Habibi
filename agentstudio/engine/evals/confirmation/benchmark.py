"""Measure the write guard's confirmation check on a model, in every language in the cases.

    LLM_PROVIDER=azure LLM_MODEL=gpt-6-luna LLM_ENDPOINT=https://... LLM_API_KEY=... \
        python -m evals.confirmation.benchmark [--repeat 3]

The one error that matters most is a false confirmation: a write the customer
did not authorise. The run exits non-zero if there is any, so a model or prompt
change cannot go in on a lower pass rate unnoticed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from api.services.pipecat.service_factory import create_llm_service_from_provider
from api.services.workflow.action_confirmation import ActionConfirmationService

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


def _service() -> ActionConfirmationService:
    llm = create_llm_service_from_provider(
        provider=os.environ.get("LLM_PROVIDER", "azure"),
        model=os.environ["LLM_MODEL"],
        api_key=os.environ["LLM_API_KEY"],
        endpoint=os.environ.get("LLM_ENDPOINT") or None,
        base_url=os.environ.get("LLM_BASE_URL") or None,
    )
    return ActionConfirmationService(llm)


async def _run(service: ActionConfirmationService, repeat: int) -> int:
    false_confirmations, misses, total, seconds = 0, Counter(), Counter(), []
    for case in CASES["confirm"]:
        turns = [("assistant", CASES["read_backs"][case["agent"]]), ("user", case["customer"])]
        for _ in range(repeat):
            started = time.monotonic()
            verdict = await service.confirm(case["action"], CASES["terms"][case["terms"]], turns)
            seconds.append(time.monotonic() - started)
            total[case["lang"]] += 1
            ok = verdict.confirmed if case["expect"] == "confirmed" else (
                verdict.status == "denied" if case["expect"] == "denied" else not verdict.confirmed)
            if not ok:
                misses[case["lang"]] += 1
                false_confirmations += verdict.confirmed
                print(f"MISS [{case['lang']}] {case['action']}: {case['customer']!r} -> "
                      f"{verdict.status}/{verdict.reason}, expected {case['expect']}")
    for case in CASES["digits"]:
        for _ in range(repeat):
            got = await service.digits(case["customer"])
            total[case["lang"]] += 1
            if got != case["expect"]:
                misses[case["lang"]] += 1
                print(f"MISS [{case['lang']}] digits: {case['customer']!r} -> {got!r}, expected {case['expect']!r}")
    for lang in sorted(total):
        print(f"{lang}: {total[lang] - misses[lang]}/{total[lang]}")
    seconds.sort()
    print(f"confirmation latency: p50 {seconds[len(seconds) // 2]:.2f}s, "
          f"p95 {seconds[int(len(seconds) * 0.95)]:.2f}s, max {seconds[-1]:.2f}s")
    print(f"false confirmations: {false_confirmations}")
    return 1 if false_confirmations else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="runs per case, to see instability")
    sys.exit(asyncio.run(_run(_service(), parser.parse_args().repeat)))


if __name__ == "__main__":
    main()
