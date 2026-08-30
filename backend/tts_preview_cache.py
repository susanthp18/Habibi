"""Disk cache for multi-provider TTS previews.

Auditioning a voice is a *comparison* task: an operator plays voice A, then B,
then A again to decide between them. That only works if A sounds the same both
times. It did not.

``/tts/preview`` had two implementations and only one was cached. Azure went
through ``azure_speech.synthesize``, which has had a disk cache all along;
everything else went through ``provider_tts.synthesize``, which had none and
whose response header was the literal string ``"miss"``. So every click on a
Cartesia, Deepgram or Fish voice re-synthesised at the vendor — and those are
sampling-based generative models that produce a different take each call.

Measured 2026-08-22, same voice and same text, three calls each:

===========  =====================  =====================================
provider     audio identical?       returned sizes
===========  =====================  =====================================
azure        yes (cache hit)        89280, 89280, 89280
cartesia     no                     90324, 89070, 85308   (6% spread)
deepgram     no                     29088, 26784, 37296   (39% spread)
fish         no                     81919, 87770, 100727  (23% spread)
===========  =====================  =====================================

Those are *duration* differences, not encoder noise — a different performance
each time. With Azure's cache cleared between calls its output stays 85248
bytes exactly, varying only in the low-order bits, which is what a
deterministic engine looks like by contrast.

The variance cannot be fixed at the vendor. Fish's own OpenAPI has no ``seed``
on ``TTSRequest`` (only ``VoiceDesignRequest`` has one), and dropping
temperature only narrows it: measured 24.8% spread at the 0.7/0.7 default,
17.9% at 0.3/0.3, 8.6% at 0.0/0.1, and ``top_p: 0`` is a 400. Deepgram and
Cartesia expose no determinism control at all. So the fix is to stop asking
twice, not to ask more carefully.

Caching also means the operator is comparing what they will actually ship,
since a re-synthesis is a *different* take rather than a second opinion on the
same one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Its own directory, not Azure's. The two caches have different key shapes and
#: different file formats, and sharing a directory would make one's eviction
#: sweep walk the other's entries.
_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "tts-preview"

_MAX_BYTES = int(os.getenv("TTS_PREVIEW_CACHE_MAX_BYTES") or str(200 * 1024 * 1024))
#: Age cap as well as size cap, so a quiet instance does not keep synthesized
#: audio on disk forever just because it never reached the size threshold.
_MAX_AGE_S = max(3600, int(os.getenv("TTS_PREVIEW_CACHE_MAX_AGE_S") or str(14 * 24 * 3600)))
_SWEEP_INTERVAL_S = 300.0

_last_sweep = 0.0
_sweep_lock = threading.Lock()

#: Bump when a change makes previously cached audio no longer representative of
#: what this code would produce now. Entries under an older version can never be
#: read, so stale audio cannot outlive the change that invalidated it.
_VERSION = "1"

_SUFFIX = ".tts"


def enabled() -> bool:
    """False disables reads *and* writes — for reproducing a vendor issue."""
    return (os.getenv("TTS_PREVIEW_CACHE") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _canonical(value: Any) -> Any:
    """A form of ``value`` where equal-sounding requests compare equal.

    JSON from a browser makes no int/float distinction, so ``speed: 1`` and
    ``speed: 1.0`` arrive as different Python types for what is one setting.
    Keyed naively they would be two cache entries, and the operator would hear
    a fresh take for a slider they had only nudged and put back.

    ``bool`` is checked first because it is a subclass of ``int`` in Python;
    without that, ``normalize: True`` would canonicalise to ``"1"`` and collide
    with a numeric 1.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # 6 significant digits: far finer than any control here, and coarse
        # enough that float noise cannot split one setting into two entries.
        return format(float(value), ".6g")
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items()) if v is not None}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def key(
    *,
    provider: str,
    voice: str,
    text: str,
    params: dict[str, Any] | None = None,
    salt: str = "",
) -> str:
    """Identity of one preview: everything that changes the audio, and nothing else.

    ``salt`` carries per-provider state that is not in ``params`` but does change
    the output — Fish's model id, which is env-selected and will change when the
    free promo ends. Leaving it out would serve audio from the old model after
    the switch, with nothing on screen to explain the difference.
    """
    material = json.dumps(
        {
            "v": _VERSION,
            "provider": provider,
            "voice": voice,
            "text": text.strip(),
            "params": _canonical(params or {}),
            "salt": salt,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _path(k: str) -> Path:
    return _CACHE_DIR / f"{k}{_SUFFIX}"


def get(k: str) -> tuple[bytes, str] | None:
    """``(audio, mime)`` for ``k``, or None. Never raises."""
    if not enabled():
        return None
    _maybe_sweep()
    try:
        # exists() then read is not atomic and the sweep above can evict this
        # very entry in between, so the read itself is the existence check.
        blob = _path(k).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except Exception:  # noqa: BLE001 - see put(); a cache must never be fatal
        logger.debug("preview cache read failed key=%s", k, exc_info=True)
        return None

    mime, sep, audio = blob.partition(b"\n")
    if not sep or not audio:
        # Truncated by a crash mid-write, or written by an older format. A miss
        # costs one synthesis; returning half a file costs a broken player.
        logger.debug("preview cache entry malformed key=%s", k)
        return None
    try:
        return audio, mime.decode("ascii")
    except UnicodeDecodeError:
        return None
    except Exception:  # noqa: BLE001 - see put(); a cache must never be fatal
        logger.debug("preview cache read failed key=%s", k, exc_info=True)
        return None


def put(k: str, audio: bytes, mime: str) -> None:
    """Store ``audio`` under ``k``. Never raises — a cache is an optimisation."""
    if not enabled() or not audio:
        return
    # A mime type with a newline would make the file unparseable on read, and
    # it would have come from a vendor response header rather than from us.
    safe_mime = (mime or "application/octet-stream").split("\n")[0].strip()
    tmp: Path | None = None
    # Deliberately `Exception`, not `OSError`. A full disk, a read-only mount
    # and a misconfigured path raise different things, and none of them is a
    # reason for the operator's preview to fail — the audio is already
    # synthesized and in hand by the time we get here. Same reasoning as the
    # sweep below.
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Written to a unique temp name and renamed, so a concurrent reader
        # sees either the old entry or the whole new one — never a partial
        # file. Two identical requests racing both write; the rename makes
        # the loser harmless rather than corrupting the winner.
        tmp = _CACHE_DIR / f"{k}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_bytes(safe_mime.encode("ascii", "replace") + b"\n" + audio)
        os.replace(tmp, _path(k))
    except Exception:  # noqa: BLE001 - a cache write must never fail a preview
        logger.debug("preview cache write failed key=%s", k, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def evict() -> None:
    """Bound the cache by age first, then total size (LRU by mtime)."""
    try:
        files = [p for p in _CACHE_DIR.glob(f"*{_SUFFIX}") if p.is_file()]
    except OSError:
        return

    now = time.time()
    total = 0
    live: list[tuple[float, int, Path]] = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > _MAX_AGE_S:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        live.append((stat.st_mtime, stat.st_size, path))
        total += stat.st_size

    if total <= _MAX_BYTES:
        return
    live.sort(key=lambda item: item[0])
    for _mtime, size, path in live:
        if total <= _MAX_BYTES:
            break
        try:
            path.unlink(missing_ok=True)
            total -= size
        except OSError:
            continue


def _maybe_sweep() -> None:
    """Throttled sweep, so a cache-hit path does not stat the whole directory."""
    global _last_sweep

    now = time.monotonic()
    if now - _last_sweep < _SWEEP_INTERVAL_S:
        return
    with _sweep_lock:
        if now - _last_sweep < _SWEEP_INTERVAL_S:
            return
        _last_sweep = now
    try:
        evict()
    except Exception:  # noqa: BLE001 - a failed sweep must not fail a preview
        logger.debug("preview cache sweep failed", exc_info=True)
