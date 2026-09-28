"""The small models the call-intelligence pass runs, on CPU.

Every model is pinned to a Hub revision and baked into the ml image by
``python -m call_intel.models fetch`` at build time; at run time the worker is
offline (``HF_HUB_OFFLINE=1``) and loads from ``ML_MODEL_DIR``. Each output
row records ``version(spec)`` so an auditor can see which model decided it.

Loaded lazily, once per process, and int8 throughout: the whole set fits the
worker's 2 GB with room for a call's audio.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from env_utils import env_int, env_str

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Spec:
    repo: str
    revision: str
    #: Files to fetch (globs); None = the whole snapshot.
    files: tuple[str, ...] | None
    #: The ONNX graph to run, relative to the snapshot.
    onnx: str | None = None


#: PII spans (GLiNER, zero-shot labels). The base model: F1 81% vs the edge
#: model's 75.5% on the publisher's PII benchmark, 197 MB as uint8.
PII = Spec(
    "knowledgator/gliner-pii-base-v1.0", "61726e0ad791dcab3e29339bbec3ad42ded65641",
    ("gliner_config.json", "added_tokens.json", "special_tokens_map.json", "spm.model",
     "tokenizer.json", "tokenizer_config.json", "onnx/model_quint8.onnx"),
    "onnx/model_quint8.onnx",
)
#: Zero-shot NLI in ~100 languages: intents and agent behaviour.
NLI = Spec(
    "Xenova/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", "0864ced79bf1ef851bfaf9dd9de0aa54d735d9d0",
    ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
     "onnx/model_int8.onnx"),
    "onnx/model_int8.onnx",
)
#: Customer sentiment, multilingual, three classes.
SENTIMENT = Spec(
    "Xenova/distilbert-base-multilingual-cased-sentiments-student", "9d9ac661fd7b0b48535a1fc99b20ae6947629e65",
    ("config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
     "onnx/model_int8.onnx"),
    "onnx/model_int8.onnx",
)
#: Word timestamps for beeping PII in the audio.
ASR = Spec("Systran/faster-whisper-base", "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66", None)

ALL = (PII, NLI, SENTIMENT, ASR)


def model_dir() -> Path:
    return Path(env_str("ML_MODEL_DIR", "/opt/models"))


def path(spec: Spec) -> Path:
    return model_dir() / spec.repo.replace("/", "--")


@lru_cache(maxsize=None)
def version(spec: Spec) -> str:
    """``repo@revision``: the pinned commit, as fetched."""
    pinned = path(spec) / ".revision"
    rev = pinned.read_text().strip() if pinned.exists() else spec.revision
    return f"{spec.repo}@{rev[:12]}"


def fetch(spec: Spec) -> None:
    """Download ``spec`` into the model dir and record the commit it resolved to."""
    from huggingface_hub import HfApi, snapshot_download

    target = path(spec)
    commit = HfApi().model_info(spec.repo, revision=spec.revision).sha
    snapshot_download(spec.repo, revision=commit, local_dir=target,
                      allow_patterns=list(spec.files) if spec.files else None)
    (target / ".revision").write_text(commit)
    logger.info("fetched %s@%s", spec.repo, commit)


def _threads() -> int:
    return max(1, env_int("ML_THREADS", 2))


_lock = threading.Lock()


class OnnxClassifier:
    """A sequence classifier exported to ONNX, run without torch."""

    def __init__(self, spec: Spec, *, max_len: int = 256):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        root = path(spec)
        config = json.loads((root / "config.json").read_text())
        self.labels = {int(k): v for k, v in config["id2label"].items()}
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_len)
        # XLM-R pads with 1, BERT-likes with 0: the config says which.
        self.tokenizer.enable_padding(pad_id=int(config.get("pad_token_id") or 0))
        options = ort.SessionOptions()
        options.intra_op_num_threads = _threads()
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root / spec.onnx), options, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}

    def probabilities(self, texts: list[str] | list[tuple[str, str]], *, batch: int = 16) -> list[dict[str, float]]:
        import numpy as np

        out: list[dict[str, float]] = []
        for k in range(0, len(texts), batch):
            chunk = texts[k:k + batch]
            enc = self.tokenizer.encode_batch(chunk)
            feed = {
                "input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
            logits = self.session.run(None, feed)[0]
            logits = logits - logits.max(axis=1, keepdims=True)
            probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
            out.extend({self.labels[i]: float(p[i]) for i in range(len(p))} for p in probs)
        return out


@lru_cache(maxsize=1)
def sentiment_model() -> OnnxClassifier:
    return OnnxClassifier(SENTIMENT)


@lru_cache(maxsize=1)
def nli_model() -> OnnxClassifier:
    return OnnxClassifier(NLI, max_len=320)


def sentiment(texts: list[str]) -> list[float]:
    """Each text's sentiment in [-1, 1]: P(positive) - P(negative)."""
    if not texts:
        return []
    return [p.get("positive", 0.0) - p.get("negative", 0.0) for p in sentiment_model().probabilities(texts)]


def entailment(pairs: list[tuple[str, str]]) -> list[float]:
    """P(premise entails hypothesis), entailment vs contradiction, per pair.

    Neutral is dropped, as in zero-shot classification: each hypothesis is an
    independent yes/no, so a turn can carry several labels.
    """
    if not pairs:
        return []
    out = []
    for p in nli_model().probabilities(pairs):
        e, c = p.get("entailment", 0.0), p.get("contradiction", 0.0)
        out.append(e / (e + c) if e + c > 0 else 0.0)
    return out


def entailment_raw(pairs: list[tuple[str, str]]) -> list[float]:
    """P(entailment) with neutral kept, per pair. Sharper than ``entailment``
    for intent detection: measured, it separates a clearly-worded intent
    (0.6-0.8) from unrelated speech (under 0.2)."""
    if not pairs:
        return []
    return [p.get("entailment", 0.0) for p in nli_model().probabilities(pairs)]


@lru_cache(maxsize=1)
def pii_model() -> Any:
    from gliner import GLiNER

    root = path(PII)
    return GLiNER.from_pretrained(str(root), load_onnx_model=True, load_tokenizer=True,
                                  onnx_model_file=PII.onnx, local_files_only=True)


def pii_spans(texts: list[str], labels: list[str], *, threshold: float) -> list[list[dict[str, Any]]]:
    """Per text, the model's entities: {start, end, label, score}."""
    if not texts:
        return []
    model = pii_model()
    with _lock:  # the GLiNER wrapper is not documented as thread-safe
        return [model.predict_entities(t, labels, threshold=threshold) if t.strip() else [] for t in texts]


@lru_cache(maxsize=1)
def asr_model() -> Any:
    from faster_whisper import WhisperModel

    return WhisperModel(str(path(ASR)), device="cpu", compute_type="int8", cpu_threads=_threads())


#: The models each pipeline stage runs. The worker keeps only these resident
#: while the stage runs: all four together measured 1.7 GB at peak on a
#: 4-minute call and a second call in the same process crossed the 2 GB limit
#: (OOM-killed on production, 2026-09-27).
STAGE_MODELS: dict[str, tuple[Any, ...]] = {
    "pii": (pii_model,),
    "audio": (asr_model,),
    "signals": (nli_model, sentiment_model),
    "qa": (),
}
_LOADERS = (pii_model, asr_model, nli_model, sentiment_model)


def keep_only(*loaders: Any) -> None:
    """Drop every cached model not in ``loaders`` and hand the memory back to
    the OS (glibc keeps freed heap otherwise, so RSS would not fall)."""
    import ctypes
    import gc

    dropped = False
    for fn in _LOADERS:
        if fn not in loaders and fn.cache_info().currsize:
            fn.cache_clear()
            dropped = True
    if not dropped:
        return
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:  # not glibc
        pass


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["fetch"]:
        for spec in ALL:
            fetch(spec)
    else:
        print({s.repo: version(s) for s in ALL})
