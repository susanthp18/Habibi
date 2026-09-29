"""Time each PII finding on the recording, so it can be beeped.

The engine's per-speaker tracks are not wall-clock aligned with its event
timestamps (TTS audio is buffered and silence padded; the drift reaches tens of
seconds over a two-minute call), so timing comes from the audio itself:

1. Speech on the speaker's channel is transcribed with word timestamps
   (faster-whisper, VAD-gated: only the speech is decoded, a fraction of the
   call). No hotwords: primed with a name, the base model drops long stretches
   of speech (49 s of one call) rather than spell it.
2. That speaker's transcript turns and the recognised words are aligned as two
   token streams (digits split one per token on both sides, so "9907" and
   "nine nine zero seven" meet). A short run spelled differently between two
   matches ("Susanth" heard as "Susant") is the same words said in that place.
3. A finding's tokens take the times of their aligned words. A token without a
   match takes the gap between its nearest matched neighbours, cut to where
   that channel has speech: the beep widens over what was said, never over
   silence or the other speaker's turn, and never moves off the words (fail
   closed). Such a segment is recorded as ``utterance_fallback`` so a reviewer
   can see it was not word-aligned.
4. A beep ends at the pause after its words when one comes within SNAP_MS: a
   word's timestamp can end before the word does.

Only channels with a finding are decoded.
"""

from __future__ import annotations

import io
import logging
import re
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np

from call_intel import pii

logger = logging.getLogger(__name__)

#: Beep this far either side of the words, so a clipped syllable is not heard.
PAD_MS = 120
#: A beep runs on to the pause after its words when the pause is this close.
SNAP_MS = 400
#: Words spelled differently between two matches are the words said there
#: only in a run this short; a longer one is the recogniser hearing otherwise.
_SUB_TOKENS = 4
_SUB_SECONDS = 3.0
#: Pieces of one beep this close together are beeped as one.
_JOIN_S = 0.3
#: Speech this short in a gap is a neighbouring word's onset or tail, not the
#: unheard word -- unless it is all the speech there is.
_MIN_PIECE_S = 0.2
_ASR_RATE = 16000
_TOKEN = re.compile(r"\d|[^\W\d_]+", re.UNICODE)


@dataclass
class Segment:
    finding: pii.Finding
    channel: str  # 'customer' | 'agent'
    start_ms: int
    end_ms: int
    source: str  # 'aligned' | 'utterance_fallback'


@dataclass
class _Token:
    norm: str
    start: float  # seconds (words) or char offset (transcript)
    end: float
    turn: int = -1


def read_stereo(wav_bytes: bytes) -> tuple[np.ndarray, np.ndarray, int]:
    """(customer, agent, rate) as float32 from the filed recording.

    Stereo is customer left, agent right; a mono file (no per-speaker tracks)
    is used for both, so a beep silences everyone at that moment.
    """
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        rate, channels = wf.getframerate(), wf.getnchannels()
        if wf.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM")
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    if channels == 2:
        return pcm[0::2], pcm[1::2], rate
    return pcm, pcm, rate


def _to_16k(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == _ASR_RATE:
        return x
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(rate, _ASR_RATE)
    return resample_poly(x, _ASR_RATE // g, rate // g).astype(np.float32)


def recognise_words(audio: np.ndarray, rate: int, *, language: str | None = None) -> list[_Token]:
    """Word-timed tokens of the speech on one channel."""
    from call_intel import models

    segments, _ = models.asr_model().transcribe(
        _to_16k(audio, rate),
        language=(language or None),
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    tokens: list[_Token] = []
    for seg in segments:
        for w in seg.words or []:
            parts = [m.group(0).lower() for m in _TOKEN.finditer(pii.normalise(w.word).text)]
            if not parts:
                continue
            step = (w.end - w.start) / len(parts)
            for k, p in enumerate(parts):
                tokens.append(_Token(p, w.start + k * step, w.start + (k + 1) * step))
    return tokens


def speech_regions(audio: np.ndarray, rate: int) -> list[tuple[float, float]]:
    """(start, end) seconds of each run of speech on one channel."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    found = get_speech_timestamps(_to_16k(audio, rate), VadOptions(min_silence_duration_ms=150, speech_pad_ms=60))
    return [(t["start"] / _ASR_RATE, t["end"] / _ASR_RATE) for t in found]


def transcript_tokens(turns: list[pii.Turn]) -> list[_Token]:
    """The turns' tokens, with character spans into each turn's original text."""
    out: list[_Token] = []
    for turn in turns:
        norm = pii.normalise(turn.text, hindi=(turn.language or "").lower().startswith("hi"))
        for m in _TOKEN.finditer(norm.text):
            s, e = norm.original(m.start(), m.end())
            out.append(_Token(m.group(0).lower(), s, e, turn.index))
    return out


def align(spoken: list[_Token], heard: list[_Token]) -> list[tuple[float, float] | None]:
    """For each transcript token, the time of the word it matched, or None.

    A short run the recogniser spelled differently between two matches
    ("susanth" heard as "susant") takes the time of the words heard in its place.
    """
    times: list[tuple[float, float] | None] = [None] * len(spoken)
    matcher = SequenceMatcher(None, [t.norm for t in spoken], [t.norm for t in heard], autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                times[a0 + k] = (heard[b0 + k].start, heard[b0 + k].end)
        elif (tag == "replace" and a1 - a0 <= _SUB_TOKENS and b1 - b0 <= _SUB_TOKENS
              and heard[b1 - 1].end - heard[b0].start <= _SUB_SECONDS):
            for k in range(a0, a1):
                times[k] = (heard[b0].start, heard[b1 - 1].end)
    return times


def _spoken_within(start: float, end: float,
                   speech: list[tuple[float, float]] | None) -> list[tuple[float, float]]:
    """The parts of [start, end] where the channel has speech; all of it when
    there is no speech map, or it found no speech there (fail closed)."""
    if speech is None:
        return [(start, end)]
    parts = [(max(start, s), min(end, e)) for s, e in speech if s < end and e > start]
    return [p for p in parts if p[1] - p[0] >= _MIN_PIECE_S] or parts or [(start, end)]


def _join(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(spans):
        if out and s - out[-1][1] <= _JOIN_S:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def _to_pause(end: float, speech: list[tuple[float, float]] | None) -> float:
    """``end`` moved on to the end of its run of speech, by at most SNAP_MS."""
    for s, e in speech or ():
        if s <= end < e:
            return min(e, end + SNAP_MS / 1000)
    return end


def time_findings(findings: list[pii.Finding], turns: list[pii.Turn], channel: str,
                  heard: list[_Token], duration_s: float,
                  speech: list[tuple[float, float]] | None = None) -> list[Segment]:
    """Segments for the findings in ``turns`` (all one speaker's).

    ``speech`` is that channel's runs of speech (``speech_regions``). Without it
    a widened beep spans its whole gap and no edge moves to a pause. A finding
    widened over several runs of speech gets a segment for each.
    """
    spoken = transcript_tokens(turns)
    times = align(spoken, heard)
    out: list[Segment] = []
    for f in findings:
        idx = [i for i, t in enumerate(spoken)
               if t.turn == f.turn_index and t.start < f.end and t.end > f.start]
        if not idx:
            continue
        spans: list[tuple[float, float]] = []
        widened = False
        for i in idx:
            timed = times[i]
            if timed is not None:
                spans.append(timed)
                continue
            # No word heard for it: the gap between its matched neighbours.
            widened = True
            before = next((times[j] for j in range(i - 1, -1, -1) if times[j]), None)
            after = next((times[j] for j in range(i + 1, len(times)) if times[j]), None)
            spans.extend(_spoken_within(before[1] if before else 0.0,
                                        after[0] if after else duration_s, speech))
        for start, end in _join(spans):
            out.append(Segment(
                f, channel,
                max(0, round(start * 1000) - PAD_MS),
                min(round(duration_s * 1000), round(_to_pause(end, speech) * 1000) + PAD_MS),
                "utterance_fallback" if widened else "aligned",
            ))
    return out


def plan(findings: list[pii.Finding], turns: list[pii.Turn], wav_bytes: bytes) -> list[Segment]:
    """Every finding's beep on the filed recording."""
    customer, agent, rate = read_stereo(wav_bytes)
    duration = len(customer) / rate
    by_speaker = {"customer": [t for t in turns if t.speaker == "customer"],
                  "agent": [t for t in turns if t.speaker == "bot"]}
    segments: list[Segment] = []
    for channel, audio in (("customer", customer), ("agent", agent)):
        own = {t.index for t in by_speaker[channel]}
        mine = [f for f in findings if f.turn_index in own]
        if not mine:
            continue
        language = next((t.language for t in by_speaker[channel] if t.language), None)
        x = _to_16k(audio, rate)
        heard = recognise_words(x, _ASR_RATE, language=(language or "")[:2] or None)
        segments.extend(time_findings(mine, by_speaker[channel], channel, heard, duration,
                                      speech_regions(x, _ASR_RATE)))
    return segments


if __name__ == "__main__":
    # Alignment without the model: "heard" words as the recogniser would give them.
    turns = [pii.Turn(0, "customer", "Sure. The last four digits are nine nine zero seven."),
             pii.Turn(1, "customer", "My card is 4111 1111 1111 1111 thanks")]
    heard = [
        _Token("sure", 1.0, 1.3), _Token("the", 1.4, 1.5), _Token("last", 1.5, 1.8),
        _Token("four", 1.8, 2.0), _Token("digits", 2.0, 2.4), _Token("are", 2.4, 2.5),
        *[_Token(d, 2.6 + 0.3 * k, 2.9 + 0.3 * k) for k, d in enumerate("9907")],
        _Token("my", 10.0, 10.2), _Token("card", 10.2, 10.5), _Token("is", 10.5, 10.6),
        # the recogniser missed the middle of the card number
        *[_Token(d, 10.7 + 0.2 * k, 10.9 + 0.2 * k) for k, d in enumerate("4111")],
        _Token("thanks", 14.0, 14.4),
    ]
    found = pii.detect([pii.Turn(-1, "bot", "What are the last four digits?"), *turns])
    segs = time_findings(found, turns, "customer", heard, 20.0)
    by = {s.finding.type: s for s in segs}
    assert by["secret"].source == "aligned" and by["secret"].start_ms == 2600 - PAD_MS, by["secret"]
    assert by["secret"].end_ms == 3800 + PAD_MS, by["secret"]
    card = by["card"]
    assert card.source == "utterance_fallback" and card.start_ms <= 10700 and card.end_ms >= 14000 - 1, card
    print("ok", [(s.finding.type, s.start_ms, s.end_ms, s.source) for s in segs])
