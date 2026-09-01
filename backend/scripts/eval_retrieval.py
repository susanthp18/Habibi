#!/usr/bin/env python
"""Retrieval-quality harness for the KB/RAG stack.

    python scripts/eval_retrieval.py --build-golden
    python scripts/eval_retrieval.py --baseline
    python scripts/eval_retrieval.py --stage-timings
    python scripts/eval_retrieval.py --scoped        # oracle product scope

Until this existed, "the chunks are wrong and confidence is low" could only be
argued from anecdote, and the embedding model was chosen by reputation rather
than measurement. It measures the real query path -- kb_retrieve.retrieve(),
not a reimplementation -- so a number moving here means the product moved.

Two families of metric, because they fail for different reasons and want
different fixes:

  product-P@1 / product-recall@k
      Did we land on the right *product*? The corpus is ten near-identical
      Protect360 documents; cross-product chunk cosine averages 0.428 against
      0.475 same-product, and 140 chunk pairs sit above 0.95 across products.
      This is the metric that moves when scoping and contextual headers land.

  strict recall@k / MRR
      Did we retrieve the specific passage that answers it? Only meaningful for
      the FAQ-derived cases, where the gold id is known exactly.

Also reports the top-1 score distribution split by correct/incorrect. That
split, not a round number, is what a confidence threshold should be read off:
the shipped 0.70 was never reachable on this corpus by any embedding model.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from env_loader import load_env  # noqa: E402

load_env()

# An 80-question sweep trips KB_RETRIEVE_MAX_PER_MIN (60/min) partway through and
# the run dies with a rate-limit error rather than a result. The harness is an
# operator tool, not a caller, so it lifts its own ceiling before kb_rate_limit
# reads it. Assigned, not setdefault: load_env() has already copied .env into
# os.environ by this point, so a setdefault would silently keep the 60/min.
os.environ["KB_RETRIEVE_MAX_PER_MIN"] = "100000"

# The shared result cache would make a second run of the same golden set report
# 15ms retrievals, which is true and useless: the harness exists to measure the
# cold path. Callers who want to measure the cache set it back explicitly.
os.environ.setdefault("KB_RESULT_CACHE_TTL_S", "0")

from sqlalchemy import text  # noqa: E402

import db  # noqa: E402
import kb_retrieve  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("eval_retrieval")

GOLDEN_PATH = BACKEND_ROOT / "tests" / "fixtures" / "kb_golden.jsonl"

# Hand-written spoken-form questions with a known product. These carry no exact
# gold passage, only a product: "which chunk answers this" is a judgement call,
# and a wrong gold id is worse than no gold id.
SEED_QUESTIONS: list[tuple[str, str]] = [
    ("does my travel plan cover trip cancellation if i fall sick", "travel"),
    ("my baggage was delayed at the airport, what can i claim", "travel"),
    ("am i covered if my flight gets cancelled because of a strike", "travel"),
    ("what is the excess i pay on a car accident claim", "car"),
    ("is my car covered if someone else was driving it", "car"),
    ("is my maid covered for hospital bills", "maid"),
    ("what happens if my helper runs away", "maid"),
    ("how much do i get for daily hospital cash", "hospital"),
    ("is pre existing condition excluded", "hospital"),
    ("am i covered if someone breaks into my house", "home"),
    ("does it cover water damage from a burst pipe", "home"),
    ("what happens if my credit card gets used fraudulently", "fraud"),
    ("someone phished me and took money from my account, am i covered", "fraud"),
    ("does it cover cancer diagnosis at an early stage", "early"),
    ("what is the waiting period before i can claim", "early"),
    ("what is the payout if i lose a limb in an accident", "personal_accident"),
    ("am i covered for accidents at work", "personal_accident"),
    ("can i pick which benefits i want in the plan", "choice"),
    ("what is the late payment fee on my statement", "collections"),
    ("how do i set up a payment plan for what i owe", "collections"),
]

_DOC_ID_RE = re.compile(r"^kb-(?:policy|benefits|faq|sop|product|compliance)-(.+)$")
_FAQ_CHUNK_RE = re.compile(r"^faq-faq-(.+)-\d+$")
_FAQ_PAIR_RE = re.compile(r"^faq-(.+)-\d+$")


def _product_of(result: dict[str, Any]) -> str:
    """Product key for a retrieved row, from its document or FAQ id.

    Document ids are kb-{type}-{product}. FAQ rows come back with chunkId
    "faq-" + the faq_pairs id, which is itself faq-{product}-NNN.
    """
    doc_id = (result.get("docId") or "").strip().lower()
    m = _DOC_ID_RE.match(doc_id)
    if m:
        return m.group(1)
    chunk_id = (result.get("chunkId") or "").strip().lower()
    m = _FAQ_CHUNK_RE.match(chunk_id)
    if m:
        return m.group(1)
    m = _FAQ_PAIR_RE.match(chunk_id)
    if m:
        return m.group(1)
    return ""


def _normalize_gold(gold_ids: list[str]) -> set[str]:
    """Accept a raw faq_pairs id or a kb_chunks id; compare against chunkId."""
    out: set[str] = set()
    for raw in gold_ids or []:
        gid = str(raw).strip()
        if not gid:
            continue
        out.add(gid)
        if gid.startswith("faq-") and not gid.startswith("faq-faq-"):
            out.add("faq-" + gid)
    return out


def build_golden(limit_per_product: int) -> int:
    """Write the golden set: seed questions + FAQ pairs as query/gold pairs.

    A FAQ pair is free supervision: the question is a real customer phrasing and
    its own row is an unambiguous gold passage.
    """
    with db.engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                    SELECT id, question
                    FROM faq_pairs
                    WHERE enabled = true AND embedding IS NOT NULL
                    ORDER BY id
                    """
                )
            )
            .mappings()
            .all()
        )

    cases: list[dict[str, Any]] = []
    for i, (query, product) in enumerate(SEED_QUESTIONS, start=1):
        cases.append(
            {
                "id": "seed-%03d" % i,
                "query": query,
                "product": product,
                "gold_ids": [],
                "origin": "handwritten",
            }
        )

    per_product: dict[str, int] = {}
    for row in rows:
        faq_pair_id = str(row["id"])
        m = _FAQ_PAIR_RE.match(faq_pair_id)
        if not m:
            continue
        product = m.group(1)
        if per_product.get(product, 0) >= limit_per_product:
            continue
        per_product[product] = per_product.get(product, 0) + 1
        cases.append(
            {
                "id": "faq-%03d" % len(cases),
                "query": (row["question"] or "").strip(),
                "product": product,
                "gold_ids": [faq_pair_id],
                "origin": "faq",
            }
        )

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN_PATH.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    return len(cases)


def load_golden() -> list[dict[str, Any]]:
    if not GOLDEN_PATH.exists():
        raise SystemExit(
            "golden set missing: %s\nRun: python scripts/eval_retrieval.py --build-golden"
            % GOLDEN_PATH
        )
    cases = []
    with GOLDEN_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: with tens of samples, interpolation invents a
    latency nobody observed."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def run(cases: list[dict[str, Any]], *, top_k: int, scoped: bool) -> dict[str, Any]:
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []

    for case in cases:
        gold_ids = _normalize_gold(case.get("gold_ids") or [])
        gold_product = (case.get("product") or "").strip().lower()
        scope = [gold_product] if (scoped and gold_product) else None

        t0 = time.perf_counter()
        try:
            payload = kb_retrieve.retrieve(
                query=case["query"],
                top_k=top_k,
                include_draft_answer=False,
                source="eval",
                product_keys=scope,
            )
        except Exception as exc:  # a failed case is data, not a crashed run
            logger.warning("case %s failed: %s", case["id"], exc)
            per_case.append({"id": case["id"], "error": str(exc)})
            continue
        wall_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(wall_ms)

        results = payload.get("results") or []
        products = [_product_of(r) for r in results]
        chunk_ids = [r.get("chunkId") for r in results]
        top_score = float(results[0]["score"]) if results else 0.0

        rank = None
        if gold_ids:
            for i, cid in enumerate(chunk_ids, start=1):
                if cid in gold_ids:
                    rank = i
                    break
        product_rank = None
        for i, p in enumerate(products, start=1):
            if p and p == gold_product:
                product_rank = i
                break

        per_case.append(
            {
                "id": case["id"],
                "origin": case.get("origin"),
                "query": case["query"],
                "goldProduct": gold_product,
                "hasGoldIds": bool(gold_ids),
                "rank": rank,
                "productRank": product_rank,
                "topScore": round(top_score, 4),
                "topProduct": products[0] if products else "",
                "wallMs": round(wall_ms, 1),
                "retrieveMs": payload.get("latencyMs"),
                "stages": payload.get("stageMs"),
            }
        )

    ok = [c for c in per_case if "error" not in c]

    report = _metrics(ok)
    report.update(
        {
            "cases": len(cases),
            "ran": len(ok),
            "errors": len(per_case) - len(ok),
            "topK": top_k,
            "scoped": scoped,
            "latencyMs": {
                "p50": round(_percentile(latencies, 0.50), 1),
                "p95": round(_percentile(latencies, 0.95), 1),
                "p99": round(_percentile(latencies, 0.99), 1),
                "max": round(max(latencies), 1) if latencies else 0.0,
            },
            "stageMs": _stage_stats(ok),
            # Split by origin, because they measure different things and the
            # easy half hides the hard half. A FAQ-derived case replays the
            # stored question verbatim, so it retrieves its own row at ~0.99
            # cosine; the handwritten cases are spoken-form paraphrases and are
            # the ones that reflect what a caller actually says. Reading only
            # the blended number is how "retrieval looks fine" survives
            # alongside "the chunks are wrong on every call".
            "byOrigin": {
                origin: _metrics([c for c in ok if c.get("origin") == origin])
                for origin in sorted({c.get("origin") or "?" for c in ok})
            },
            "perCase": per_case,
        }
    )
    return report


def _stage_stats(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    totals: dict[str, list[float]] = {}
    for c in rows:
        for name, val in (c.get("stages") or {}).items():
            totals.setdefault(name, []).append(float(val))
    return {
        name: {
            "p50": round(_percentile(vals, 0.50), 1),
            "p95": round(_percentile(vals, 0.95), 1),
        }
        for name, vals in sorted(totals.items())
    }


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Quality metrics over one slice of cases."""
    strict = [c for c in rows if c["hasGoldIds"]]

    def _at(subset: list[dict[str, Any]], key: str, k: int) -> float:
        if not subset:
            return 0.0
        return sum(1 for c in subset if c[key] is not None and c[key] <= k) / len(subset)

    correct = [c["topScore"] for c in rows if c["productRank"] == 1]
    wrong = [c["topScore"] for c in rows if c["productRank"] != 1]

    return {
        "n": len(rows),
        "productP@1": round(_at(rows, "productRank", 1), 4),
        "productRecall@3": round(_at(rows, "productRank", 3), 4),
        "productRecall@5": round(_at(rows, "productRank", 5), 4),
        "strictCases": len(strict),
        "recall@1": round(_at(strict, "rank", 1), 4),
        "recall@3": round(_at(strict, "rank", 3), 4),
        "recall@5": round(_at(strict, "rank", 5), 4),
        "mrr": (
            round(sum(1.0 / c["rank"] for c in strict if c["rank"]) / len(strict), 4)
            if strict
            else 0.0
        ),
        "topScoreMean": round(statistics.fmean([c["topScore"] for c in rows]), 4) if rows else 0.0,
        "topScoreMax": round(max((c["topScore"] for c in rows), default=0.0), 4),
        "scoreWhenProductCorrect": round(statistics.fmean(correct), 4) if correct else 0.0,
        "scoreWhenProductWrong": round(statistics.fmean(wrong), 4) if wrong else 0.0,
        "aboveLegacy0_70": sum(1 for c in rows if c["topScore"] >= 0.70),
    }


def _print_report(report: dict[str, Any], *, show_stages: bool) -> None:
    print()
    print(
        "  cases=%s/%s  topK=%s  scoped=%s"
        % (report["ran"], report["cases"], report["topK"], report["scoped"])
    )
    if report["errors"]:
        print("  ERRORS: %s" % report["errors"])
    print()
    print("  Product discrimination")
    print("    product-P@1        %.3f" % report["productP@1"])
    print("    product-recall@3   %.3f" % report["productRecall@3"])
    print("    product-recall@5   %.3f" % report["productRecall@5"])
    print()
    print("  Passage retrieval (%s cases with an exact gold id)" % report["strictCases"])
    print("    recall@1           %.3f" % report["recall@1"])
    print("    recall@3           %.3f" % report["recall@3"])
    print("    recall@5           %.3f" % report["recall@5"])
    print("    MRR                %.3f" % report["mrr"])
    print()
    print("  Score calibration")
    print(
        "    top-1 mean         %.3f   (max %.3f)"
        % (report["topScoreMean"], report["topScoreMax"])
    )
    print("    when product right %.3f" % report["scoreWhenProductCorrect"])
    print("    when product wrong %.3f" % report["scoreWhenProductWrong"])
    print("    >= legacy 0.70     %s/%s" % (report["aboveLegacy0_70"], report["ran"]))
    print()
    lat = report["latencyMs"]
    print("  Latency (wall, per retrieve call)")
    print(
        "    p50 %.0f ms   p95 %.0f ms   p99 %.0f ms   max %.0f ms"
        % (lat["p50"], lat["p95"], lat["p99"], lat["max"])
    )
    if show_stages and report["stageMs"]:
        print()
        print("  Stage breakdown")
        for name, vals in report["stageMs"].items():
            print("    %-14s p50 %7.1f ms   p95 %7.1f ms" % (name, vals["p50"], vals["p95"]))
    by_origin = report.get("byOrigin") or {}
    if len(by_origin) > 1:
        print()
        print("  By origin (handwritten = spoken-form paraphrase; faq = verbatim stored question)")
        print("    %-12s %5s  %8s  %8s  %8s  %9s" % ("origin", "n", "prodP@1", "recall@3", "top1mean", ">=0.70"))
        for origin, m in by_origin.items():
            print(
                "    %-12s %5d  %8.3f  %8.3f  %8.3f  %5d/%-3d"
                % (
                    origin,
                    m["n"],
                    m["productP@1"],
                    m["recall@3"],
                    m["topScoreMean"],
                    m["aboveLegacy0_70"],
                    m["n"],
                )
            )
    print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--build-golden",
        action="store_true",
        help="regenerate the golden set from faq_pairs + seed questions",
    )
    ap.add_argument(
        "--faq-per-product", type=int, default=6, help="FAQ-derived cases per product"
    )
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cases")
    ap.add_argument(
        "--scoped",
        action="store_true",
        help="pass the gold product as product_keys (measures the scoping ceiling)",
    )
    ap.add_argument(
        "--stage-timings", action="store_true", help="print the per-stage p50/p95 breakdown"
    )
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="also write the report to artifacts/retrieval_baseline.json",
    )
    ap.add_argument("--out", type=str, default="", help="write the full report JSON here")
    args = ap.parse_args()

    if args.build_golden:
        n = build_golden(args.faq_per_product)
        print("wrote %s cases -> %s" % (n, GOLDEN_PATH))
        return 0

    cases = load_golden()
    if args.limit:
        cases = cases[: args.limit]
    report = run(cases, top_k=args.top_k, scoped=args.scoped)
    _print_report(report, show_stages=args.stage_timings)

    out_path = Path(args.out) if args.out else None
    if args.baseline and not out_path:
        out_path = BACKEND_ROOT.parent / "artifacts" / "retrieval_baseline.json"
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("  report -> %s" % out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
