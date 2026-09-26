"""Which knowledge-base product is a question about? Decided by meaning, not keywords.

Six places used to answer this with their own hand-typed word lists
(``context._STRONG_ALIASES``, ``kb._PRODUCT_QUERY_HINTS``,
``kb_plan._named_product_keys``, ``kb_retrieve.OTHER_PRODUCT_TOKENS`` ...). They
disagreed with each other and with the way people talk: on VS-7956F27B36
"I want something for my travel to Singapore" was travel insurance to a person
and nothing at all to the lists, so the search ran against the collections
corpus and the caller heard a product name and no answer. No list survives
"I'm flying to Dubai for my cousin's wedding" or a caller who says "the one for
my helper".

Three signals now, strongest first:

1. **The conversation model says which product** -- the ``product`` argument of
   ``search_knowledge_base``. It has the whole call in front of it, resolves
   "that one", and costs nothing extra: it is writing the tool call anyway.
   Validated here against the live catalog; an invalid value is ignored, never
   trusted.
2. **Semantic routing** (:meth:`ProductRouter.route`). Every product has a set of
   caller phrasings in ``kb_product_utterances``, written by the analysis model
   from that product's own documents (``kb_products.py``) plus any an operator
   adds. The question's embedding -- already computed for the vector search, so
   this adds no model call -- is compared against them, and retrieval is scoped
   only on a clear winner: a score floor *and* a margin over the runner-up.
3. **What the call already settled on** (the caller's ``fallback``), used when
   routing is not sure. "And my age is 23" is about the product from the last
   turn.

Anything weaker searches every product and lets relevance decide, with the
closest products softly boosted. A wrong hard scope hides the one document that
had the answer, so uncertainty must widen the search, never narrow it.

A product *title* said outright ("Home Protect360", "home protect three sixty")
is matched literally before any of this: a proper noun is not a paraphrase
problem, and an embedding quirk must not be able to overrule it.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Sequence

from env_utils import env_float, env_str

logger = logging.getLogger(__name__)

# Route tiers, strongest first.
EXPLICIT = "explicit"    # the conversation model named it (tool argument)
NAMED = "named"          # a product title was said outright
ROUTED = "routed"        # semantic routing, clear winner
FALLBACK = "fallback"    # routing unsure; what the call already settled on
UNCERTAIN = "uncertain"  # routing unsure, nothing settled: search all, boost these
GENERAL = "general"      # a question about any product ("what does it cover?")
NONE = "none"

SCOPING_TIERS = frozenset({EXPLICIT, NAMED, ROUTED, FALLBACK})

#: The collections corpus is a product key but not an insurance product.
COLLECTIONS_KEY = "collections"


# Calibrated with scripts/eval_product_routing.py --sweep against
# tests/fixtures/product_routing.jsonl (68 hand-written phrasings, none seen by
# the generator), 2026-09-25, on profiles with FAQ-question anchors and top-2
# aggregation. The margin does the work: at 0.45 / 0.10 it measured 45
# correct / 2 wrong / 21 unsure (repeat runs differ by one: Azure embeddings are
# not bit-stable); at 0.45 / 0.04 it was 54 / 4 / 10. A wrong scope hides the
# answer while an unsure one searches everything, so precision wins. The two
# misses are "gaadi ka insurance chahiye" (romanised Hindi, weak in this
# embedding model) and "my domestic helper was sick so I couldn't go to the
# bank" -- both are decided by the models on the search path, which scored 64/68
# on the same set; routing only decides alone for the background enricher.
def min_score() -> float:
    """Best-product similarity below which routing never scopes."""
    return env_float("KB_ROUTE_MIN_SCORE", 0.45)


def min_margin() -> float:
    """Lead over the runner-up product required to scope."""
    return env_float("KB_ROUTE_MIN_MARGIN", 0.10)


def soft_min_score() -> float:
    """Below this the question is about no product in particular."""
    return env_float("KB_ROUTE_SOFT_MIN_SCORE", 0.35)


#: Phrasings of two different products this similar to each other say nothing
#: about which one is meant ("what does it cover?"), so neither counts.
AMBIGUOUS_UTTERANCE_SIM = 0.92

#: The "no product in particular" class: model-written questions that apply to
#: every product (kb_products._reconcile_generic). A question nearest these is
#: not pinned on a product, and a product phrasing this close to one of them
#: is too generic to vote.
GENERIC_KEY = "_generic"
GENERIC_OVERLAP_SIM = 0.85


def aggregation() -> str:
    """How a product's phrasing similarities become one score: ``max`` or ``top2``
    (mean of its two best). Measured by scripts/eval_product_routing.py."""
    value = env_str("KB_ROUTE_AGG", "top2").lower()
    return value if value in {"max", "top2"} else "top2"

_REFRESH_S = 60.0
#: After a failed load, how long until the next attempt.
_FAIL_RETRY_S = 30.0

# ---------------------------------------------------------------------------
# Literal titles
# ---------------------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_WORDS = frozenset(_UNITS) | frozenset(_TEENS) | frozenset(_TENS) | {"hundred"}
_TOKEN = re.compile(r"[a-z]+|[0-9]+")


def _is_number(tok: str) -> bool:
    return tok.isdigit() or tok in _NUMBER_WORDS


def _run_digits(run: list[str]) -> str:
    """Spoken numbers as the digits a title carries: "three sixty" and
    "three six zero" are how people say 360; "three hundred and sixty" is
    arithmetic; "twenty four" is 24."""
    groups: list[str] = []
    i = 0
    while i < len(run):
        tok = run[i]
        if tok.isdigit():
            groups.append(tok)
            i += 1
        elif tok in _TENS:
            value = _TENS[tok]
            if i + 1 < len(run) and _UNITS.get(run[i + 1], 0) > 0:
                value += _UNITS[run[i + 1]]
                i += 1
            groups.append(str(value))
            i += 1
        elif tok == "hundred":
            groups.append("100")
            i += 1
        else:
            value = _UNITS.get(tok, _TEENS.get(tok, 0))
            i += 1
            if i < len(run) and run[i] == "hundred":
                value *= 100
                i += 1
                if i < len(run) and run[i] == "and":
                    i += 1
                if i < len(run) and run[i] in _TENS:
                    value += _TENS[run[i]]
                    i += 1
                    if i < len(run) and _UNITS.get(run[i], 0) > 0:
                        value += _UNITS[run[i]]
                        i += 1
                elif i < len(run) and (run[i] in _UNITS or run[i] in _TEENS):
                    value += _UNITS.get(run[i], _TEENS.get(run[i], 0))
                    i += 1
            groups.append(str(value))
    return "".join(groups)


def normalize(text: str | None) -> str:
    """Lower-case words, spoken numbers as digits glued to the word before.

    "Protect360", "protect 360", "protect three sixty" and "protect three
    hundred and sixty" all become ``protect360``, so a title said aloud matches
    the title on the document however the transcript wrote it.
    """
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    tokens = _TOKEN.findall(folded.lower())
    merged: list[str] = []
    i = 0
    while i < len(tokens):
        if not _is_number(tokens[i]):
            merged.append(tokens[i])
            i += 1
            continue
        run = [tokens[i]]
        i += 1
        while i < len(tokens) and (
            _is_number(tokens[i])
            or (
                tokens[i] == "and"
                and run[-1] == "hundred"
                and i + 1 < len(tokens)
                and _is_number(tokens[i + 1])
            )
        ):
            run.append(tokens[i])
            i += 1
        merged.append(_run_digits(run))
    glued: list[str] = []
    for tok in merged:
        if tok.isdigit() and glued and glued[-1].isalpha():
            glued[-1] += tok
        else:
            glued.append(tok)
    return " ".join(glued)


@lru_cache(maxsize=512)
def _phrase_re(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])")


def title_forms(title: str) -> tuple[str, ...]:
    """How a title gets said: whole, cut after the brand, brand without its number.

    "Early Protect360 Plus" -> early protect360 plus / early protect360 /
    early protect. Recognition drops the tail and the number more often than it
    keeps them. A form must have two words: "early" alone is an adverb.
    """
    words = normalize(title).split()
    forms = [" ".join(words)] if len(words) >= 2 else []
    for i, word in enumerate(words):
        stem = word.rstrip("0123456789")
        if i > 0 and stem != word and stem.isalpha():
            forms += [" ".join(words[: i + 1]), " ".join(words[:i] + [stem])]
            # "Personal Accident Protect360" is also said "personal accident";
            # a one-word prefix ("travel") is an everyday word, not a name.
            if i >= 2:
                forms.append(" ".join(words[:i]))
            break
    return tuple(dict.fromkeys(forms))


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductProfile:
    key: str
    title: str
    summary: str | None = None
    #: Other names the documents use for it ("Family Protect360"), matched
    #: exactly like the title. Written by kb_products from the documents.
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Route:
    tier: str = NONE
    keys: tuple[str, ...] = ()
    #: Best product similarity and its lead over the runner-up.
    score: float | None = None
    margin: float | None = None
    #: Uncertain tier: the closest products, boosted but not filtered to.
    candidates: tuple[str, ...] = ()
    #: Top products with their similarity, for the log line and the test panel.
    scores: tuple[tuple[str, float], ...] = ()

    @property
    def key(self) -> str | None:
        return self.keys[0] if self.keys else None

    @property
    def scoped(self) -> bool:
        return self.tier in SCOPING_TIERS and bool(self.keys)

    @property
    def insurance(self) -> bool:
        """Settled on a product that is not the collections corpus."""
        return self.scoped and any(k != COLLECTIONS_KEY for k in self.keys)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "keys": list(self.keys),
            "score": None if self.score is None else round(self.score, 4),
            "margin": None if self.margin is None else round(self.margin, 4),
            "candidates": list(self.candidates),
            "scores": [{"productKey": k, "score": round(s, 4)} for k, s in self.scores],
        }

    def describe(self) -> str:
        top = ", ".join(f"{k}={s:.3f}" for k, s in self.scores) or "-"
        return f"tier={self.tier} keys={','.join(self.keys) or '-'} top=[{top}]"


class ProductRouter:
    """Routing over one tenant's catalog. No I/O after construction."""

    def __init__(
        self,
        products: Iterable[ProductProfile],
        utterances: Iterable[tuple[str, str, Sequence[float]]] = (),
    ) -> None:
        import numpy as np

        self.products: tuple[ProductProfile, ...] = tuple(p for p in products if p.key)
        self._by_key = {p.key: p for p in self.products}
        self._forms = [
            (form, p.key)
            for p in self.products
            for name in (p.title, *p.names)
            for form in title_forms(name)
        ]

        labels: list[str] = []
        rows: list[Any] = []
        for key, _text, vector in utterances:
            if (key in self._by_key or key == GENERIC_KEY) and vector is not None and len(vector):
                labels.append(key)
                rows.append(vector)
        self.excluded = 0
        self._matrix = self._labels = None
        self._generic = None
        if rows:
            matrix = np.asarray(rows, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix = matrix / np.where(norms == 0, 1.0, norms)
            label_arr = np.asarray(labels)
            is_generic = label_arr == GENERIC_KEY
            sims = matrix @ matrix.T
            # A phrasing nearly identical to another product's phrasing cannot
            # tell them apart; drop both rather than let it cast a vote.
            other = (label_arr[:, None] != label_arr[None, :]) & ~is_generic[:, None] & ~is_generic[None, :]
            ambiguous = ((sims >= AMBIGUOUS_UTTERANCE_SIM) & other).any(axis=1)
            # A product phrasing that reads like a question about any product
            # ("how do I claim?") would pin every such question on it.
            too_generic = ~is_generic & (
                (sims[:, is_generic] >= GENERIC_OVERLAP_SIM).any(axis=1) if is_generic.any() else False
            )
            # And a "generic" phrasing that clearly points at one product
            # ("home burglary coverage?") is not generic: it would swallow that
            # product's real questions. Judged against the product phrasings.
            if is_generic.any() and (~is_generic).any():
                prod_idx = np.where(~is_generic)[0]
                prod_labels = label_arr[prod_idx].tolist()
                for g in np.where(is_generic)[0].tolist():
                    best: dict[str, float] = {}
                    for lab, sim in zip(prod_labels, sims[g, prod_idx].tolist()):
                        # A near-duplicate is a product phrasing that is itself
                        # generic (dropped below), not evidence against this one.
                        if sim < GENERIC_OVERLAP_SIM:
                            best[lab] = max(best.get(lab, -1.0), sim)
                    ranked_g = sorted(best.values(), reverse=True)
                    if len(ranked_g) > 1 and ranked_g[0] >= 0.6 and ranked_g[0] - ranked_g[1] >= 0.08:
                        is_generic[g] = False
                        ambiguous[g] = True  # dropped, and counted
            drop = ambiguous | too_generic
            self.excluded = int(drop.sum())
            product_rows = ~drop & ~is_generic
            self._matrix = matrix[product_rows]
            self._labels = label_arr[product_rows]
            if is_generic.any():
                self._generic = matrix[is_generic]
            if not len(self._labels):
                self._matrix = self._labels = None

    def __len__(self) -> int:
        return len(self.products)

    def keys(self) -> tuple[str, ...]:
        return tuple(self._by_key)

    def has(self, key: str | None) -> bool:
        return bool(key) and key in self._by_key

    def title(self, key: str | None) -> str | None:
        p = self._by_key.get(key or "")
        return p.title if p else None

    def summary(self, key: str | None) -> str | None:
        p = self._by_key.get(key or "")
        return p.summary if p else None

    @property
    def utterance_count(self) -> int:
        return 0 if self._matrix is None else int(self._matrix.shape[0])

    def menu(self) -> list[dict[str, Any]]:
        """Key, title and summary per product -- what the models are shown."""
        return [
            {"productKey": p.key, "title": p.title, **({"summary": p.summary} if p.summary else {})}
            for p in self.products
        ]

    def match_key(self, value: str | None) -> str | None:
        """A tool argument naming a product: its key or its title, else ``None``."""
        said = normalize(value)
        if not said:
            return None
        for p in self.products:
            if said in {normalize(p.key.replace("_", " ")), normalize(p.key)} or said in title_forms(p.title):
                return p.key
        named = self.titles_named(said)
        return named[0] if len(named) == 1 else None

    def titles_named(self, text: str | None) -> list[str]:
        """Products whose title was said outright, in order of mention."""
        said = normalize(text)
        if not said:
            return []
        hits = sorted(
            (m.start(), -len(form), key)
            for form, key in self._forms
            if (m := _phrase_re(form).search(said))
        )
        return list(dict.fromkeys(key for _, _, key in hits))

    def _unit(self, vector: Sequence[float] | None) -> Any:
        import numpy as np

        if vector is None or not len(vector):
            return None
        v = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(v))
        return None if norm == 0 else v / norm

    def similarities(self, vector: Sequence[float] | None, *, agg: str | None = None) -> list[tuple[str, float]]:
        """One score per product, highest first."""
        v = self._unit(vector)
        if self._matrix is None or v is None:
            return []
        sims = (self._matrix @ v).tolist()
        per: dict[str, list[float]] = {}
        for label, sim in zip(self._labels.tolist(), sims):
            per.setdefault(label, []).append(sim)
        mode = agg or aggregation()
        scores = {}
        for label, values in per.items():
            values.sort(reverse=True)
            scores[label] = values[0] if mode == "max" or len(values) < 2 else (values[0] + values[1]) / 2
        return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)

    def generic_similarity(self, vector: Sequence[float] | None) -> float | None:
        """Best similarity to the "no product in particular" phrasings."""
        v = self._unit(vector)
        if self._generic is None or v is None:
            return None
        return float((self._generic @ v).max())

    def is_product_question(self, vector: Sequence[float] | None) -> bool:
        """Nearest to an insurance product (not collections), and near enough."""
        ranked = self.similarities(vector) if vector is not None else []
        generic = self.generic_similarity(vector) or 0.0
        best = ranked[0] if ranked else (None, 0.0)
        if generic >= soft_min_score() and generic >= best[1]:
            return True  # an insurance question, just not about one product
        return best[0] is not None and best[0] != COLLECTIONS_KEY and best[1] >= soft_min_score()

    def route(
        self,
        vector: Sequence[float] | None,
        *,
        text: str | None = None,
        fallback: Sequence[str] | None = None,
    ) -> Route:
        """Scope for one question. Never raises."""
        named = self.titles_named(text)
        ranked = self.similarities(vector) if vector is not None else []
        top = tuple(ranked[:3])
        score = ranked[0][1] if ranked else None
        margin = (ranked[0][1] - ranked[1][1]) if len(ranked) > 1 else score
        if named:
            return Route(tier=NAMED, keys=tuple(named), score=score, margin=margin, scores=top)
        generic = self.generic_similarity(vector) if vector is not None else None
        about_any = generic is not None and score is not None and generic >= score
        if (
            not about_any
            and ranked
            and score is not None
            and score >= min_score()
            and (margin or 0.0) >= min_margin()
        ):
            return Route(tier=ROUTED, keys=(ranked[0][0],), score=score, margin=margin, scores=top)
        settled = tuple(k for k in (fallback or ()) if self.has(k))
        # A collections node's own corpus is the wrong fallback for a question
        # that is plainly about insurance, even if routing cannot tell which
        # product: "does it cover medical costs abroad" belongs in the product
        # documents, searched whole, not in the repayment FAQ.
        insurance_ish = (
            ranked and ranked[0][0] != COLLECTIONS_KEY and score is not None and score >= soft_min_score()
        ) or (about_any and (generic or 0.0) >= soft_min_score())
        if settled == (COLLECTIONS_KEY,) and insurance_ish:
            settled = ()
        if settled:
            return Route(tier=FALLBACK, keys=settled, score=score, margin=margin, scores=top)
        if about_any:
            # "What does it cover?" with nothing settled: every product equally.
            return Route(tier=GENERAL, score=score, margin=margin, scores=top)
        if ranked and score is not None and score >= soft_min_score():
            close = tuple(k for k, s in ranked[:3] if score - s <= min_margin() * 2)
            return Route(tier=UNCERTAIN, candidates=close, score=score, margin=margin, scores=top)
        return Route(tier=NONE, score=score, margin=margin, scores=top)


# ---------------------------------------------------------------------------
# Loading: catalog + profiles + phrasings, per tenant and snapshot
# ---------------------------------------------------------------------------

_cache: dict[tuple[str, str | None], tuple[float, tuple, ProductRouter]] = {}
_cache_lock = threading.Lock()
_EMPTY: ProductRouter | None = None


def _empty() -> ProductRouter:
    global _EMPTY
    if _EMPTY is None:
        _EMPTY = ProductRouter(())
    return _EMPTY


def _cache_key(kb_snapshot_id: str | None) -> tuple[str, str | None]:
    import tenant_context

    return (tenant_context.current_tenant(), kb_snapshot_id or None)


def _parse_vector(raw: Any) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    try:
        return [float(x) for x in json.loads(str(raw))]
    except (TypeError, ValueError):
        return None


def _signature(conn: Any, tenant: str, catalog: list[dict[str, Any]]) -> tuple:
    from sqlalchemy import text

    row = conn.execute(
        text(
            """
            SELECT (SELECT max(updated_at) FROM kb_products WHERE tenant_id = :t) AS p,
                   (SELECT count(*) FROM kb_product_utterances WHERE tenant_id = :t) AS n,
                   (SELECT max(created_at) FROM kb_product_utterances WHERE tenant_id = :t) AS u
            """
        ),
        {"t": tenant},
    ).mappings().first()
    return (
        tuple((str(c.get("productKey")), str(c.get("title"))) for c in catalog),
        str(row["p"]) if row else None,
        int(row["n"] or 0) if row else 0,
        str(row["u"]) if row else None,
    )


def _build(conn: Any, tenant: str, catalog: list[dict[str, Any]]) -> ProductRouter:
    from sqlalchemy import text

    summaries = {
        str(r["product_key"]): r["summary"]
        for r in conn.execute(
            text("SELECT product_key, summary FROM kb_products WHERE tenant_id = :t"),
            {"t": tenant},
        ).mappings()
    }
    rows = conn.execute(
        text(
            """
            SELECT product_key, text, origin, embedding::text AS embedding
              FROM kb_product_utterances
             WHERE tenant_id = :t AND embedding IS NOT NULL
            """
        ),
        {"t": tenant},
    ).mappings().all()
    names: dict[str, list[str]] = {}
    for r in rows:
        if r["origin"] == "title":
            names.setdefault(str(r["product_key"]), []).append(str(r["text"]))
    products = [
        ProductProfile(
            key=str(c["productKey"]).strip().lower(),
            title=str(c.get("title") or c["productKey"]),
            summary=summaries.get(str(c["productKey"]).strip().lower()),
            names=tuple(names.get(str(c["productKey"]).strip().lower(), ())),
        )
        for c in catalog
        if c.get("productKey")
    ]
    return ProductRouter(
        products,
        ((str(r["product_key"]), str(r["text"]), _parse_vector(r["embedding"])) for r in rows),
    )


def load(kb_snapshot_id: str | None = None) -> ProductRouter:
    """The tenant's router. Never raises; blocks on the database.

    Checks a cheap signature at most once a minute and rebuilds only when the
    catalog, a profile or a phrasing changed. Call it from a worker thread;
    code on the event loop uses :func:`cached`.
    """
    key = _cache_key(kb_snapshot_id)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < _REFRESH_S:
        return hit[2]
    try:
        import db
        import kb_retrieve

        catalog = kb_retrieve.catalog(kb_snapshot_id=kb_snapshot_id)
        with db.engine.begin() as conn:
            sig = _signature(conn, key[0], catalog)
            if hit and hit[1] == sig:
                router = hit[2]
            else:
                router = _build(conn, key[0], catalog)
                logger.info(
                    "product router built · tenant=%s · snapshot=%s · products=%s · "
                    "phrasings=%d · ambiguous_dropped=%d",
                    key[0],
                    key[1],
                    ",".join(router.keys()) or "-",
                    router.utterance_count,
                    router.excluded,
                )
                missing = [p.key for p in router.products if p.summary is None]
                if missing:
                    logger.warning(
                        "product router: no generated profile for %s -- routing on "
                        "titles only; run scripts/kb_product_profiles.py",
                        ",".join(missing),
                    )
    except Exception:
        logger.warning(
            "product router load failed (tenant=%s snapshot=%s) -- %s; retrying in %.0fs",
            key[0],
            key[1],
            "keeping the previous one" if hit else "no routing",
            _FAIL_RETRY_S,
            exc_info=True,
        )
        # Remember the failure. Without this every knowledge-base call paid a
        # full connection timeout while the database was unreachable -- found
        # by a test run that took 7.5 minutes instead of seconds.
        fallback_router = hit[2] if hit else _empty()
        with _cache_lock:
            _cache[key] = (now - _REFRESH_S + _FAIL_RETRY_S, hit[1] if hit else None, fallback_router)
        return fallback_router
    with _cache_lock:
        _cache[key] = (now, sig, router)
    return router


def cached(kb_snapshot_id: str | None = None) -> ProductRouter:
    """The last loaded router, however old, without touching the database."""
    with _cache_lock:
        hit = _cache.get(_cache_key(kb_snapshot_id))
    return hit[2] if hit else _empty()


def invalidate() -> None:
    """Forget every cached router -- after profiles or phrasings change."""
    with _cache_lock:
        _cache.clear()

