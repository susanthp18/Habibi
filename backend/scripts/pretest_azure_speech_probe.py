"""Azure Speech capability probes — synthetic audio only. No PSTN. No DB audio.

Harness-only. Not imported by the voice runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

ARTIFACT = Path(os.environ.get("SLM_PRETEST_DIR") or r"D:\Hackathon\artifacts\slm-pretest")
FFMPEG = os.environ.get(
    "FFMPEG",
    r"C:\Users\SusanthP\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0-full_build\bin\ffmpeg.exe",
)

UTTERANCES = {
    "en": "Please pay rupees twelve thousand three hundred forty five today.",
    "hi": "Namaste, main kal UPI se paisa bhej dunga.",
    "ta": "Vanakkam, naan next week pay panren.",
    "hinglish": "Paisa nahi hai bhai, naukri chali gayi, give me ten days.",
}
AMOUNT_SET = [
    "The outstanding is rupees twelve thousand three hundred forty five.",
    "Please confirm rupees one lakh twenty thousand.",
    "The EMI is rupees two thousand five hundred point five zero.",
]
VOICES = {
    "en-IN": "en-IN-NeerjaNeural",
    "hi-IN": "hi-IN-SwaraNeural",
    "ta-IN": "ta-IN-PallaviNeural",
}


def _region() -> str:
    return (os.getenv("AZURE_SPEECH_REGION") or "").strip()


def _key() -> str:
    return (os.getenv("AZURE_SPEECH_KEY") or "").strip()


def inspect_sdk() -> dict:
    import azure.cognitiveservices.speech as speechsdk

    names = dir(speechsdk)
    pid_names = []
    try:
        pid_names = [p.name for p in speechsdk.PropertyId]
    except Exception as exc:
        pid_names = [f"enum_error:{type(exc).__name__}"]
    wanted = [
        "AutoDetectSourceLanguageConfig",
        "PhraseListGrammar",
        "SourceLanguageConfig",
        "SpeechConfig",
        "SpeechRecognizer",
        "SpeechSynthesizer",
    ]
    present = {n: (n in names or hasattr(speechsdk, n)) for n in wanted}
    try:
        import azure.cognitiveservices.speech.languageconfig as lc

        present["languageconfig.AutoDetectSourceLanguageConfig"] = hasattr(
            lc, "AutoDetectSourceLanguageConfig"
        )
    except Exception as exc:
        present["languageconfig"] = f"{type(exc).__name__}"
    psr_props = [n for n in pid_names if "Post" in n or "Psr" in n or "LanguageId" in n or "Phrase" in n]
    return {
        "sdk_version": getattr(speechsdk, "__version__", None),
        "symbols": present,
        "property_ids_matching": psr_props,
        "property_id_count": len(pid_names) if isinstance(pid_names, list) else 0,
    }


def _ffmpeg(args: list[str]) -> None:
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args]
    subprocess.run(cmd, check=True)


def tts_wav(text: str, voice: str, dest: Path) -> dict:
    import azure_speech

    t0 = time.perf_counter()
    try:
        result = azure_speech.synthesize(text, voice_name=voice, force_fresh=True)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}:{exc}", "voice": voice}
    mp3 = dest.with_suffix(".mp3")
    mp3.write_bytes(result["audio"])
    _ffmpeg(["-i", str(mp3), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dest)])
    return {
        "ok": True,
        "voice": voice,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
        "bytes": dest.stat().st_size,
        "chars": len(text),
    }


def recognize_file(path: Path, *, language: str, extras: dict | None = None) -> dict:
    import azure.cognitiveservices.speech as speechsdk

    extras = extras or {}
    conf = speechsdk.SpeechConfig(subscription=_key(), region=_region())
    conf.speech_recognition_language = language
    notes = []
    if extras.get("psr"):
        applied = False
        for pid_name in (
            "SpeechServiceResponse_PostProcessingOption",
            "SpeechServiceResponse_RequestWordLevelTimestamps",
        ):
            pid = getattr(speechsdk.PropertyId, pid_name, None)
            if pid is None:
                continue
            try:
                conf.set_property(pid, extras.get("psr_value") or "TrueText")
                notes.append(f"set {pid_name}")
                applied = True
            except Exception as exc:
                notes.append(f"{pid_name}:{type(exc).__name__}")
        if not applied:
            notes.append("no_psr_property")
    if extras.get("lid_continuous"):
        pid = getattr(speechsdk.PropertyId, "SpeechServiceConnection_LanguageIdMode", None)
        if pid is not None:
            conf.set_property(pid, "Continuous")
            notes.append("LanguageIdMode=Continuous")
        else:
            notes.append("no_LanguageIdMode")

    audio = speechsdk.audio.AudioConfig(filename=str(path))
    recognizer_kwargs = {"speech_config": conf, "audio_config": audio}
    detected = None
    if extras.get("auto_detect"):
        try:
            from azure.cognitiveservices.speech.languageconfig import AutoDetectSourceLanguageConfig

            auto = AutoDetectSourceLanguageConfig(languages=extras["auto_detect"])
            recognizer_kwargs["auto_detect_source_language_config"] = auto
            notes.append(f"auto_detect={extras['auto_detect']}")
        except Exception as exc:
            notes.append(f"auto_detect_fail:{type(exc).__name__}:{exc}")

    rec = speechsdk.SpeechRecognizer(**recognizer_kwargs)
    if extras.get("phrases"):
        try:
            grammar = speechsdk.PhraseListGrammar.from_recognizer(rec)
            for p in extras["phrases"]:
                grammar.addPhrase(p)
            notes.append(f"phrases={len(extras['phrases'])}")
        except Exception as exc:
            notes.append(f"phrase_fail:{type(exc).__name__}:{exc}")

    t0 = time.perf_counter()
    result = rec.recognize_once_async().get()
    ms = int((time.perf_counter() - t0) * 1000)
    reason = str(result.reason)
    text = result.text or ""
    err = None
    if result.reason == speechsdk.ResultReason.Canceled:
        det = result.cancellation_details
        err = f"{det.reason}:{det.error_details}"
    props = {}
    try:
        props["language"] = result.properties.get(
            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult, ""
        )
    except Exception:
        pass
    return {
        "ok": result.reason == speechsdk.ResultReason.RecognizedSpeech,
        "reason": reason,
        "latency_ms": ms,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "text_len": len(text),
        "error": err,
        "notes": notes,
        "detected_locale": props.get("language") or None,
        "seed_hash": hashlib.sha256(path.name.encode()).hexdigest()[:12],
        # Keep recognized text for WER against invented seeds only (not borrower audio).
        "text": text,
    }


def mai_transcribe(path: Path) -> dict:
    import httpx

    region = _region()
    key = _key()
    urls = [
        f"https://{region}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
        f"https://{region}.stt.speech.microsoft.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15",
    ]
    definition = json.dumps(
        {"locales": ["en-IN", "hi-IN"], "enhancedMode": {"enabled": True, "model": "MAI-Transcribe-2"}}
    )
    out = []
    for url in urls:
        t0 = time.perf_counter()
        try:
            with path.open("rb") as fh:
                resp = httpx.post(
                    url,
                    headers={"Ocp-Apim-Subscription-Key": key},
                    files={"audio": (path.name, fh, "audio/wav")},
                    data={"definition": definition},
                    timeout=45.0,
                )
            body = (resp.text or "")[:300]
            out.append(
                {
                    "url_host": url.split("/")[2],
                    "status": resp.status_code,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "body_prefix": body,
                }
            )
        except Exception as exc:
            out.append(
                {
                    "url_host": url.split("/")[2],
                    "status": None,
                    "error": f"{type(exc).__name__}:{exc}",
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                }
            )
    return {"attempts": out}


def g711_roundtrip(src_wav: Path, dest_dir: Path) -> Path:
    mulaw = dest_dir / (src_wav.stem + ".ulaw.wav")
    back = dest_dir / (src_wav.stem + ".g711.16k.wav")
    _ffmpeg(["-i", str(src_wav), "-ar", "8000", "-ac", "1", "-c:a", "pcm_mulaw", str(mulaw)])
    _ffmpeg(["-i", str(mulaw), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(back)])
    return back


def wer(ref: str, hyp: str) -> float:
    r = ref.lower().split()
    h = hyp.lower().split()
    if not r:
        return 0.0 if not h else 1.0
    dp = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        dp[i][0] = i
    for j in range(len(h) + 1):
        dp[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            cost = 0 if r[i - 1] == h[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[-1][-1] / len(r)


def main() -> int:
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "region": _region(),
        "key_set": bool(_key()),
        "sdk": inspect_sdk(),
        "probes": [],
    }
    if not _key() or not _region():
        report["fatal"] = "AZURE_SPEECH_KEY or REGION empty"
        (ARTIFACT / "05-azure-speech.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("missing speech credentials (presence only)", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="slm-azure-") as tmp:
        tmp_path = Path(tmp)
        tts_results = {}
        for locale, voice in VOICES.items():
            lang = locale.split("-")[0]
            text = UTTERANCES["hi" if lang == "hi" else "ta" if lang == "ta" else "en"]
            wav = tmp_path / f"{locale}.wav"
            rec = tts_wav(text, voice, wav)
            rec["locale"] = locale
            rec["seed"] = text
            tts_results[locale] = rec
            report["probes"].append({"feature": f"tts_{locale}", **{k: v for k, v in rec.items() if k != "seed"}})

        for locale, rec in tts_results.items():
            if not rec.get("ok"):
                continue
            wav = tmp_path / f"{locale}.wav"
            stt = recognize_file(wav, language=locale)
            stt["feature"] = f"stt_mono_{locale}"
            stt["wer_vs_seed"] = wer(rec["seed"], stt.get("text") or "")
            report["probes"].append(stt)

        hi = tts_results.get("hi-IN")
        if hi and hi.get("ok"):
            wav = tmp_path / "hi-IN.wav"
            for feat, extras in (
                ("phrase_list_hi-IN", {"phrases": ["UPI", "Protect360", "EMI"]}),
                ("psr_hi-IN", {"psr": True, "psr_value": "TrueText"}),
            ):
                row = recognize_file(wav, language="hi-IN", extras=extras)
                row["feature"] = feat
                report["probes"].append(row)

        en = tts_results.get("en-IN")
        if en and en.get("ok"):
            wav = tmp_path / "en-IN.wav"
            row = recognize_file(
                wav, language="en-IN", extras={"phrases": ["twelve thousand", "Protect360"]}
            )
            row["feature"] = "phrase_list_en-IN"
            report["probes"].append(row)
            row = recognize_file(wav, language="en-IN", extras={"psr": True})
            row["feature"] = "psr_en-IN"
            report["probes"].append(row)

        ta = tts_results.get("ta-IN")
        if ta and ta.get("ok"):
            wav = tmp_path / "ta-IN.wav"
            row = recognize_file(wav, language="ta-IN", extras={"phrases": ["Protect360"]})
            row["feature"] = "phrase_list_ta-IN_expected_unsupported"
            report["probes"].append(row)
            row = recognize_file(wav, language="ta-IN", extras={"psr": True})
            row["feature"] = "psr_ta-IN_expected_absent"
            report["probes"].append(row)

        # Hinglish clip via hi-IN TTS of mixed text, then LID / multilingual attempts.
        mix_wav = tmp_path / "hinglish.wav"
        mix = tts_wav(UTTERANCES["hinglish"], VOICES["hi-IN"], mix_wav)
        mix["feature"] = "tts_hinglish_hi-voice"
        report["probes"].append({k: v for k, v in mix.items() if k != "seed"} | {"feature": mix["feature"]})
        if mix.get("ok"):
            row = recognize_file(
                mix_wav,
                language="hi-IN",
                extras={"auto_detect": ["hi-IN", "en-IN"], "lid_continuous": True},
            )
            row["feature"] = "continuous_lid_hi_en"
            row["wer_vs_seed"] = wer(UTTERANCES["hinglish"], row.get("text") or "")
            report["probes"].append(row)
            row = recognize_file(
                mix_wav,
                language="en-IN",
                extras={"psr": True, "psr_value": "Multilingual"},
            )
            row["feature"] = "multilingual_psr_open_range_attempt"
            report["probes"].append(row)
            report["mai"] = mai_transcribe(mix_wav)

        for i, phrase in enumerate(AMOUNT_SET):
            wav = tmp_path / f"amount_{i}.wav"
            syn = tts_wav(phrase, VOICES["en-IN"], wav)
            syn["feature"] = f"tts_amount_{i}"
            report["probes"].append({k: v for k, v in syn.items() if k != "seed"} | {"feature": syn["feature"], "seed": phrase})
            if syn.get("ok"):
                stt = recognize_file(wav, language="en-IN")
                stt["feature"] = f"stt_amount_{i}"
                stt["wer_vs_seed"] = wer(phrase, stt.get("text") or "")
                report["probes"].append(stt)

        messy = []
        seeds = [
            ("en-IN", UTTERANCES["en"]),
            ("hi-IN", UTTERANCES["hi"]),
            ("ta-IN", UTTERANCES["ta"]),
            ("hi-IN", UTTERANCES["hinglish"]),
            ("en-IN", AMOUNT_SET[0]),
        ]
        for i, (locale, seed) in enumerate(seeds):
            wav = tmp_path / f"messy_{i}.wav"
            syn = tts_wav(seed, VOICES[locale], wav)
            if not syn.get("ok"):
                messy.append({"i": i, "tts_ok": False, "error": syn.get("error")})
                continue
            roundtrip = g711_roundtrip(wav, tmp_path)
            stt = recognize_file(roundtrip, language=locale)
            messy.append(
                {
                    "i": i,
                    "locale": locale,
                    "seed_sha256": hashlib.sha256(seed.encode()).hexdigest(),
                    "wer": wer(seed, stt.get("text") or ""),
                    "stt_ok": stt.get("ok"),
                    "reason": stt.get("reason"),
                    "error": stt.get("error"),
                    "text": stt.get("text"),
                }
            )
        report["messy_stt"] = messy

    (ARTIFACT / "05-azure-speech.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {ARTIFACT / '05-azure-speech.json'} probes={len(report['probes'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
