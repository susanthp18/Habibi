"""Measure semantic product routing and calibrate its thresholds.

    python scripts/eval_product_routing.py            # report at current thresholds
    python scripts/eval_product_routing.py --sweep    # plus the threshold grid

Reads tests/fixtures/product_routing.jsonl: caller phrasings written by hand,
none of them produced by the profile generator, labelled with the product they
mean -- or ``none`` for a turn that names no product ("and my age is 23",
"what does it cover"), which must NOT be scoped, or ``collections``.

The error that matters is a **wrong scope**: a hard filter to the wrong product
hides every document that had the answer. An abstention costs little -- the
search runs across every product, and the call's settled product is the
fallback. So the sweep ranks thresholds by correct scopes minus three times
wrong ones, and prints the confusion at the chosen point.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from env_loader import load_env  # noqa: E402

load_env()

FIXTURE = BACKEND_ROOT / "tests" / "fixtures" / "product_routing.jsonl"
WRONG_WEIGHT = 3.0


def _score(router, rows: list[dict], s_min: float, m_min: float, agg: str) -> dict:
    """Drive the real ``ProductRouter.route`` at these thresholds."""
    from agent_core import product_resolver as pr

    os.environ["KB_ROUTE_MIN_SCORE"] = str(s_min)
    os.environ["KB_ROUTE_MIN_MARGIN"] = str(m_min)
    os.environ["KB_ROUTE_AGG"] = agg
    correct = wrong = abstain = 0
    errors, abstains = [], []
    for r in rows:
        route = router.route(r["vector"], text=r["text"])
        got = route.key if route.tier in (pr.NAMED, pr.ROUTED) else None
        label = r["label"]
        if got is None:
            if label == "none":
                correct += 1
            else:
                abstain += 1
                abstains.append((r["text"], label, route.tier, route.scores[:2]))
        elif got == label:
            correct += 1
        else:
            wrong += 1
            errors.append((r["text"], label, got, route.scores[:2]))
    return {"correct": correct, "wrong": wrong, "abstain": abstain, "errors": errors, "abstains": abstains}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--llm", action="store_true", help="Also measure the planner's product choice")
    args = parser.parse_args()

    import azure_openai
    from agent_core import product_resolver

    cases = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line.strip()]
    router = product_resolver.load()
    if not router.utterance_count:
        print("router has no phrasings -- run scripts/kb_product_profiles.py first")
        return 2
    vectors = azure_openai.embed_texts([c["text"] for c in cases])
    rows = []
    for case, vec in zip(cases, vectors):
        label = case["label"] if case["label"] == "none" or router.has(case["label"]) else None
        if label is not None:
            rows.append({"text": case["text"], "label": label, "vector": vec})
    print(
        f"{len(rows)} cases · {len(router)} products · {router.utterance_count} phrasings "
        f"({router.excluded} dropped as ambiguous or generic)"
    )

    s_now, m_now, agg_now = product_resolver.min_score(), product_resolver.min_margin(), product_resolver.aggregation()
    now = _score(router, rows, s_now, m_now, agg_now)
    print(
        f"\ncurrent  min_score={s_now:.3f} min_margin={m_now:.3f} agg={agg_now}: "
        f"correct={now['correct']} wrong={now['wrong']} abstain={now['abstain']}"
    )
    for text, label, got, top in now["errors"]:
        print(f"  WRONG   {text!r}: meant {label}, scoped {got}  top={[(k, round(v, 3)) for k, v in top]}")
    for text, label, tier, top in now["abstains"]:
        print(f"  abstain {text!r}: meant {label} ({tier})  top={[(k, round(v, 3)) for k, v in top]}")

    # Is it about an insurance product at all? (the text channel's intent gate)
    gate_ok = gate_n = 0
    for r in rows:
        if r["label"] == "none":
            continue
        want = r["label"] != product_resolver.COLLECTIONS_KEY
        gate_n += 1
        gate_ok += router.is_product_question(r["vector"]) == want
    print(f"\nproduct-question gate: {gate_ok}/{gate_n} right")

    if args.llm:
        # The model path: the planner, shown every product's key, title and
        # summary, chooses the scope -- as it does on every search_knowledge_base
        # call where the conversation model did not name the product itself.
        from agent_core.tools import kb_plan

        ok = wrong_n = abstain_n = 0
        for r in rows:
            plan = kb_plan.plan_retrieval(
                customer_text=r["text"], available_products=router.menu(), budget=20.0
            )
            keys = list(plan.product_keys or [])
            # Several products including the right one still finds the answer.
            if len(keys) > 1 and r["label"] in keys:
                ok += 1
                continue
            got = keys[0] if len(keys) == 1 else ("multi:" + ",".join(keys) if keys else None)
            if plan.source != kb_plan.SOURCE_LLM:
                print(f"  planner fell back on {r['text']!r}")
            if got is None:
                ok += r["label"] == "none"
                abstain_n += r["label"] != "none"
                if r["label"] != "none":
                    print(f"  llm abstain {r['text']!r}: meant {r['label']}")
            elif got == r["label"]:
                ok += 1
            else:
                wrong_n += 1
                print(f"  llm WRONG {r['text']!r}: meant {r['label']}, chose {got}")
        print(f"\nplanner: correct={ok} wrong={wrong_n} abstain={abstain_n}")

    if args.sweep:
        grid = []
        for agg in ("max", "top2"):
            for i in range(0, 17):
                s_min = 0.25 + i * 0.025
                for j in range(0, 11):
                    m_min = j * 0.01
                    res = _score(router, rows, s_min, m_min, agg)
                    grid.append((res["correct"] - WRONG_WEIGHT * res["wrong"], s_min, m_min, agg, res))
        grid.sort(key=lambda g: (g[0], -g[4]["wrong"], g[2], g[1]), reverse=True)
        print("\nbest thresholds (utility = correct - 3*wrong):")
        for utility, s_min, m_min, agg, res in grid[:10]:
            print(
                f"  agg={agg:<4} min_score={s_min:.3f} min_margin={m_min:.2f}  utility={utility:.0f}  "
                f"correct={res['correct']} wrong={res['wrong']} abstain={res['abstain']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
