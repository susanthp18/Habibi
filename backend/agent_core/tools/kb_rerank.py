"""Local cross-encoder reranking for KB passages.

Dense retrieval answers "what is this passage about"; it does not answer "does
this passage answer *that* question". On this corpus the gap is measurable: the
right passage is in the top 5 far more often than it is at rank 1. A
cross-encoder reads the query and the passage together and closes most of it.

Why local rather than an API: the deployment target is on-premise inside a bank,
where a per-turn call to a hosted rerank service is not going to survive review.
This runs in-process on ONNX Runtime, which the voice image already carries for
Silero VAD, so the marginal cost is the model file.

What this replaces
------------------
``kb_plan.judge_passages`` used to do two jobs — reorder the candidates, and
decide whether they answer the question at all — with an LLM call carrying a
guaranteed 3.5s floor on every voice turn. It has been removed. A cross-encoder
does the first job directly and, because it returns a *calibrated* relevance
score, is also the only cheap candidate for the second.

Nothing does the second job numerically today: the 0.70 gate the judge
backstopped thresholded raw cosine, which over the golden set predicts retrieval
success at AUC 0.548 — a coin flip. Abstention now happens at generation time,
and the top1-top2 margin (AUC 0.975) is reported for calibration.

Three properties this module must have, in order
------------------------------------------------
1. **It must never be the reason a turn is slow.** Every call takes a deadline
   and returns the input order untouched when it cannot finish in time. There is
   no partial state to unwind: reranking is a permutation, so falling back is
   always safe.
2. **It must never be the reason a turn fails.** A missing model file, a cold
   cache, a bad tokenizer — all of it degrades to dense order and a debug log.
3. **It must be measurable before it is trusted.** Off unless
   ``KB_RERANK_ENABLED`` says otherwise, and every call reports how long it took
   so the eval harness can decide whether it fits the budget on real hardware.

Ordering note: rerank *after* product scoping, never instead of it. Measured on
the 80-case golden set, reranking an unscoped candidate list moved handwritten
product-P@1 from 0.800 to 0.550 — the model happily promotes the semantically
right passage from the wrong Protect360 product, because ten near-identical
corpora look equally relevant to a question that never names one.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Sequence

logger = logging.getLogger(__name__)

# MiniLM-L-6 is the smallest cross-encoder that still reranks well, and the only
# size with a plausible shot at a voice latency budget on CPU. Overridable so a
# deployment with headroom can trade up without a code change.
DEFAULT_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"

# Candidates and passage length are the two knobs that actually move cost: the
# model is quadratic in sequence length and linear in pair count. 12 x 700 chars
# matches what the LLM judge was already given (_MAX_CANDIDATES=12,
# _MAX_SNIPPET_CHARS=700), so this is not a quality regression against it.
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_MAX_CHARS = 700
DEFAULT_BUDGET_MS = 250.0

_lock = threading.Lock()
_encoder: Any | None = None
_load_failed = False


def _flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def enabled() -> bool:
    """Whether reranking is switched on. Off by default — see module docstring."""
    return _flag("KB_RERANK_ENABLED", False)


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        return max(low, min(high, int((os.getenv(name) or "").strip() or default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float, *, low: float, high: float) -> float:
    try:
        return max(low, min(high, float((os.getenv(name) or "").strip() or default)))
    except (TypeError, ValueError):
        return default


def max_candidates() -> int:
    return _int_env("KB_RERANK_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES, low=2, high=50)


def max_chars() -> int:
    return _int_env("KB_RERANK_MAX_CHARS", DEFAULT_MAX_CHARS, low=120, high=4000)


def budget_ms() -> float:
    return _float_env("KB_RERANK_BUDGET_MS", DEFAULT_BUDGET_MS, low=20.0, high=5000.0)


def model_name() -> str:
    return (os.getenv("KB_RERANK_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _get_encoder() -> Any | None:
    """Load the cross-encoder once per process. ``None`` means "run without it"."""
    global _encoder, _load_failed
    if _encoder is not None or _load_failed:
        return _encoder
    with _lock:
        if _encoder is not None or _load_failed:
            return _encoder
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            started = time.perf_counter()
            # CPUExecutionProvider is pinned deliberately. onnxruntime advertises
            # AzureExecutionProvider ahead of CPU in this image, and letting the
            # default provider list stand risks routing an in-process rerank
            # through a remote endpoint — the opposite of the reason this module
            # is local at all.
            _encoder = TextCrossEncoder(
                model_name=model_name(),
                providers=["CPUExecutionProvider"],
            )
            logger.info(
                "kb reranker loaded model=%s in %.0fms",
                model_name(),
                (time.perf_counter() - started) * 1000.0,
            )
        except Exception:
            # A reranker that cannot load is a reranker that does not run. The
            # caller keeps dense order and the turn is unaffected.
            _load_failed = True
            logger.warning("kb reranker unavailable; falling back to dense order", exc_info=True)
            return None
    return _encoder


def prewarm() -> bool:
    """Load and exercise the model so the first real turn does not pay for it.

    A cold ONNX session costs a graph load plus a first-inference allocation.
    Paying that inside a live call is exactly the kind of one-off spike that
    reads as "the bot froze".
    """
    if not enabled():
        return False
    encoder = _get_encoder()
    if encoder is None:
        return False
    try:
        list(encoder.rerank("warm up the session", ["warm up the session"]))
        return True
    except Exception:
        logger.debug("kb reranker prewarm failed", exc_info=True)
        return False


def passage_text(result: dict[str, Any], limit: int | None = None) -> str:
    """The text the cross-encoder scores: heading first, then the passage.

    The heading carries the section name ("General Exclusions", "Baggage Delay")
    and is often the strongest single signal about what a chunk is for.
    """
    cap = limit if limit is not None else max_chars()
    heading = (result.get("heading") or "").strip()
    snippet = (result.get("snippet") or "").strip()
    joined = f"{heading}\n{snippet}" if heading else snippet
    return joined[:cap]


def rerank(
    query: str,
    results: Sequence[dict[str, Any]],
    *,
    budget_s: float | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Reorder ``results`` by cross-encoder relevance to ``query``.

    Returns ``(ordered, info)``. ``info`` always carries ``applied`` and
    ``elapsed_ms``, plus ``reason`` when it did not run and ``scores`` when it
    did. Never raises: the worst case is the input order and a debug log.

    Only the head of the list is reranked. The tail is already ranked by cosine
    and is not going to be promoted into the top few by any reordering that
    matters, so paying for it buys nothing.
    """
    ordered = list(results)
    info: dict[str, Any] = {"applied": False, "elapsed_ms": 0.0}
    if not query or not ordered:
        info["reason"] = "empty"
        return ordered, info
    if not enabled():
        info["reason"] = "disabled"
        return ordered, info

    started = time.perf_counter()
    encoder = _get_encoder()
    if encoder is None:
        info["reason"] = "unavailable"
        info["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return ordered, info

    head_n = min(len(ordered), limit if limit is not None else max_candidates())
    head, tail = ordered[:head_n], ordered[head_n:]
    budget = budget_s if budget_s is not None else (budget_ms() / 1000.0)

    try:
        docs = [passage_text(r) for r in head]
        scores = list(encoder.rerank(query, docs))
    except Exception:
        logger.debug("kb rerank failed; keeping dense order", exc_info=True)
        info["reason"] = "error"
        info["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return ordered, info

    elapsed = time.perf_counter() - started
    info["elapsed_ms"] = round(elapsed * 1000.0, 2)

    if len(scores) != len(head):
        # A short score list cannot be zipped safely, and guessing which
        # passages it covers would silently reorder the wrong ones.
        info["reason"] = "score_count_mismatch"
        return ordered, info

    if elapsed > budget:
        # Deliberately checked *after* the call rather than enforced with a
        # timeout: onnxruntime inference is not interruptible, so the honest
        # options are "use the result" or "discard it". Discarding keeps the
        # ordering a caller sees consistent with the budget they asked for, and
        # the breach is reported so it stops being enabled at this size.
        info["reason"] = "over_budget"
        info["budget_ms"] = round(budget * 1000.0, 2)
        logger.warning(
            "kb rerank took %.0fms over a %.0fms budget; keeping dense order",
            elapsed * 1000.0,
            budget * 1000.0,
        )
        return ordered, info

    reordered = [r for _, r in sorted(zip(scores, head), key=lambda pair: -pair[0])]
    info["applied"] = True
    info["scores"] = [round(float(s), 4) for s in sorted(scores, reverse=True)]
    return reordered + tail, info
