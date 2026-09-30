"""Measure the write guard's confirmation check on a model, and gate on it.

    LLM_PROVIDER=azure LLM_MODEL=gpt-6-luna LLM_ENDPOINT=https://... LLM_API_KEY=... \
        python -m evals.confirmation.benchmark [--repeat 3]
    python -m evals.confirmation.benchmark --self-check     # the gate itself, no model

Each check runs under the engine's own timeout (a timeout is a miss, as it is
in a call). The run exits non-zero when any false confirmation occurs or when
any expected kind -- confirmed, denied, not_confirmed, digits -- or any
language falls below the accuracy in ``cases.json``'s gate: a model or prompt
change that loses real confirmations or stops reading digits fails as surely
as one that confirms too much.
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

from api.services.workflow.action_confirmation import (
    CHECK_TIMEOUT_SECS,
    UNAVAILABLE,
    ActionConfirmationService,
    Confirmation,
    Verdict,
)

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))


def _service() -> ActionConfirmationService:
    from api.services.pipecat.service_factory import create_llm_service_from_provider

    llm = create_llm_service_from_provider(
        provider=os.environ.get("LLM_PROVIDER", "azure"),
        model=os.environ["LLM_MODEL"],
        api_key=os.environ["LLM_API_KEY"],
        endpoint=os.environ.get("LLM_ENDPOINT") or None,
        base_url=os.environ.get("LLM_BASE_URL") or None,
    )
    return ActionConfirmationService(llm)


async def _timed(coro, fallback):
    started = time.monotonic()
    try:
        value = await asyncio.wait_for(coro, timeout=CHECK_TIMEOUT_SECS)
    except Exception:
        value = fallback
    return value, time.monotonic() - started


def _passes(expect: str, verdict: Verdict) -> bool:
    if expect == "confirmed":
        return verdict.confirmed
    if expect == "denied":
        return verdict.status is Confirmation.DENIED
    return not verdict.confirmed


async def _run(service, repeat: int) -> int:
    gate = CASES["gate"]
    passed, total = Counter(), Counter()
    false_confirmations, seconds = 0, {"confirm": [], "digits": []}
    for case in CASES["confirm"]:
        turns = [("assistant", CASES["read_backs"][case["agent"]]), ("user", case["customer"])]
        for _ in range(repeat):
            verdict, took = await _timed(
                service.confirm(case["action"], CASES["terms"][case["terms"]], turns), UNAVAILABLE)
            seconds["confirm"].append(took)
            ok = _passes(case["expect"], verdict)
            for bucket in (f"kind:{case['expect']}", f"lang:{case['lang']}"):
                total[bucket] += 1
                passed[bucket] += ok
            if not ok:
                false_confirmations += verdict.confirmed
                print(f"MISS [{case['lang']}] {case['action']}: {case['customer']!r} -> "
                      f"{verdict.status}/{verdict.reason}, expected {case['expect']}")
    question = CASES["read_backs"]["digits_en"]
    for case in CASES["digits"]:
        for _ in range(repeat):
            got, took = await _timed(service.digits([("assistant", question), ("user", case["customer"])]), "")
            seconds["digits"].append(took)
            ok = got == case["expect"]
            for bucket in ("kind:digits", f"lang:{case['lang']}"):
                total[bucket] += 1
                passed[bucket] += ok
            if not ok:
                print(f"MISS [{case['lang']}] digits: {case['customer']!r} -> {got!r}, expected {case['expect']!r}")

    scenarios = len(CASES["confirm"]) + len(CASES["digits"])
    print(f"{scenarios} scenarios x {repeat} = {sum(total[b] for b in total if b.startswith('kind:'))} checks")
    failing = []
    for bucket in sorted(total):
        accuracy = passed[bucket] / total[bucket]
        mark = "" if accuracy >= gate["min_accuracy"] else "  <- below gate"
        failing += [bucket] if mark else []
        print(f"{bucket}: {passed[bucket]}/{total[bucket]} ({accuracy:.0%}){mark}")
    for kind, times in seconds.items():
        if times:
            times.sort()
            print(f"{kind} latency: p50 {times[len(times) // 2]:.2f}s, "
                  f"p95 {times[int(len(times) * 0.95)]:.2f}s, max {times[-1]:.2f}s")
    print(f"false confirmations: {false_confirmations}")
    return 1 if failing or false_confirmations > gate["false_confirmations"] else 0


class _Inert:
    """Refuses everything and reads no digits: the gate must reject it."""

    async def confirm(self, *_a) -> Verdict:
        return UNAVAILABLE

    async def digits(self, *_a) -> str:
        return ""


class _Yes:
    """Confirms everything: the gate must reject it."""

    async def confirm(self, *_a) -> Verdict:
        return Verdict(Confirmation.CONFIRMED, "agreed")

    async def digits(self, *_a) -> str:
        return "2324"


def _self_check() -> int:
    for fake in (_Inert(), _Yes()):
        assert asyncio.run(_run(fake, 1)) == 1, f"the gate passed {type(fake).__name__}"
    print("self-check: the gate rejects a service that refuses everything and one that confirms everything")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="runs per case, to see instability")
    parser.add_argument("--self-check", action="store_true", help="check the gate itself, with no model")
    args = parser.parse_args()
    sys.exit(_self_check() if args.self_check else asyncio.run(_run(_service(), args.repeat)))


if __name__ == "__main__":
    main()
