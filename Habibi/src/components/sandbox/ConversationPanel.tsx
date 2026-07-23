import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ChevronDown,
  ChevronRight,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Play,
  Send,
  SkipForward,
  Volume2,
} from "lucide-react";
import { groundedLabel, type SandboxChunkHit } from "@/api/sandbox";
import { previewTts } from "@/api/prompt-studio";
import { transcribeAudio } from "@/api/speech";
import type { VoiceConfig } from "@/data/prompt-studio-seed";
import { INTENT_LABEL, type IntentKey, type SandboxTurn } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";
import type { SandboxMode } from "./SandboxHeader";

export type LiveCallChrome = {
  status: "idle" | "connecting" | "live" | "ended";
  muted: boolean;
  elapsedSec: number;
  voiceLabel?: string;
  onStart: () => void;
  onEnd: () => void;
  onToggleMute: () => void;
};

type Props = {
  mode: SandboxMode;
  turns: SandboxTurn[];
  onSend: (text: string) => void;
  onPlayNext: () => void;
  onSkipEnd: () => void;
  awaiting: boolean;
  canPlayNext: boolean;
  voice?: VoiceConfig | null;
  autoPlayTts?: boolean;
  onAutoPlayTts?: (v: boolean) => void;
  /** Intent expected for the last scripted customer turn (scorecard). */
  lastExpectedIntent?: IntentKey | null;
  live?: LiveCallChrome | null;
};

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  }
  return "";
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function ConversationPanel({
  mode,
  turns,
  onSend,
  onPlayNext,
  onSkipEnd,
  awaiting,
  canPlayNext,
  voice,
  autoPlayTts = false,
  onAutoPlayTts,
  lastExpectedIntent,
  live,
}: Props) {
  const [draft, setDraft] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const wantRecordingRef = useRef(false);
  const lastSpokenBotId = useRef<string | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, awaiting]);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      mediaRecorderRef.current = null;
    };
  }, []);

  // Auto-play newest bot turn in text mode when enabled.
  useEffect(() => {
    if (!autoPlayTts || mode !== "text" || !voice) return;
    const lastBot = [...turns].reverse().find((t) => t.role === "bot" && t.text.trim());
    if (!lastBot || lastBot.id === lastSpokenBotId.current) return;
    if (lastBot.latencyMs === 0 && (lastBot.tokens ?? 0) === 0) return; // skip template opening
    lastSpokenBotId.current = lastBot.id;
    void playBotText(lastBot.text, voice).catch(() => undefined);
  }, [turns, autoPlayTts, mode, voice]);

  const send = () => {
    const t = draft.trim();
    if (!t) return;
    onSend(t);
    setDraft("");
  };

  const holdStart = async () => {
    if (awaiting || transcribing || recording || mode === "live") return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      toast.error("Microphone not available in this browser");
      return;
    }
    wantRecordingRef.current = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // The user may have released during the async permission/getUserMedia gap;
      // if so, don't start the recorder — just release the mic.
      if (!wantRecordingRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      toast.error("Mic permission denied — type your turn instead");
      setRecording(false);
    }
  };

  const holdEnd = async () => {
    wantRecordingRef.current = false;
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      setRecording(false);
      return;
    }
    setRecording(false);
    setTranscribing(true);

    const blob = await new Promise<Blob>((resolve) => {
      recorder.onstop = () => {
        resolve(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.stop();
    });

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRecorderRef.current = null;

    try {
      if (blob.size < 256) {
        toast.message("Recording too short");
        return;
      }
      const ext = blob.type.includes("mp4") ? "mp4" : blob.type.includes("ogg") ? "ogg" : "webm";
      const result = await transcribeAudio(blob, { filename: `clip.${ext}` });
      const text = (result.text || "").trim();
      if (!text) {
        toast.message("No speech detected — try again or type");
        return;
      }
      onSend(text);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Transcription failed");
    } finally {
      setTranscribing(false);
    }
  };

  const micBusy = awaiting || transcribing;
  const lastCustomer = [...turns].reverse().find((t) => t.role === "customer" && t.intent);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface-page">
      {mode === "live" && live && (
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border-token)] bg-surface-card px-4 py-2">
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[11px] font-medium capitalize",
              live.status === "live"
                ? "bg-emerald-50 text-emerald-700"
                : live.status === "connecting"
                  ? "bg-amber-50 text-amber-700"
                  : "bg-surface-sunken text-text-secondary",
            )}
          >
            {live.status}
          </span>
          {(live.status === "live" || live.status === "connecting") && (
            <span className="font-mono text-[11px] text-text-muted">{formatElapsed(live.elapsedSec)}</span>
          )}
          {live.voiceLabel && (
            <span className="text-[11px] text-text-muted">Voice: {live.voiceLabel}</span>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {live.status === "idle" || live.status === "ended" ? (
              <button
                type="button"
                onClick={live.onStart}
                className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-2.5 py-1.5 text-[12px] font-medium text-white hover:bg-brand-primary-dark"
              >
                <Phone className="h-3.5 w-3.5" /> Start call
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={live.onToggleMute}
                  className="rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken"
                >
                  {live.muted ? "Unmute" : "Mute"}
                </button>
                <button
                  type="button"
                  onClick={live.onEnd}
                  className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-[12px] font-medium text-red-700 hover:bg-red-100"
                >
                  <PhoneOff className="h-3.5 w-3.5" /> End
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {mode === "text" && lastCustomer?.intent && lastExpectedIntent && (
        <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border-token)] bg-surface-sunken/60 px-4 py-1.5 text-[11px]">
          <span className="text-text-muted">Scorecard</span>
          <span className="rounded-full bg-surface-card px-2 py-0.5 text-text-secondary">
            expected {INTENT_LABEL[lastExpectedIntent]}
          </span>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 font-medium",
              lastCustomer.intent === lastExpectedIntent
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-50 text-amber-800",
            )}
          >
            got {INTENT_LABEL[lastCustomer.intent as IntentKey] ?? lastCustomer.intent}
            {lastCustomer.intent === lastExpectedIntent ? " · match" : " · mismatch"}
          </span>
        </div>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {turns.map((t) => (
            <TurnBubble key={t.id} turn={t} voice={mode === "text" ? voice : null} />
          ))}
          {awaiting && (
            <div className="flex items-center gap-2 self-start rounded-full bg-surface-card px-3 py-1.5 text-[11px] text-text-muted shadow-sm">
              <span className="flex gap-0.5">
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:120ms]" />
                <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-primary [animation-delay:240ms]" />
              </span>
              bot is thinking… (retrieve + chat)
            </div>
          )}
          {transcribing && (
            <div className="flex items-center gap-2 self-end rounded-full bg-surface-card px-3 py-1.5 text-[11px] text-text-muted shadow-sm">
              Transcribing…
            </div>
          )}
        </div>
      </div>

      {mode === "text" && (
        <div className="shrink-0 border-t border-[var(--border-token)] bg-surface-card px-4 py-3">
          <div className="mx-auto flex max-w-3xl items-center gap-2">
            <button
              type="button"
              onClick={onPlayNext}
              disabled={!canPlayNext || micBusy}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[11.5px] hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
              title="Play next scripted customer turn (spends tokens)"
            >
              <Play className="h-3.5 w-3.5" /> Next
            </button>
            <button
              type="button"
              onClick={onSkipEnd}
              disabled={!canPlayNext || micBusy}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[11.5px] hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
              title="Play up to 3 remaining scripted turns"
            >
              <SkipForward className="h-3.5 w-3.5" /> Skip
            </button>
            {onAutoPlayTts && (
              <label className="inline-flex items-center gap-1 text-[11px] text-text-muted">
                <input
                  type="checkbox"
                  checked={autoPlayTts}
                  onChange={(e) => onAutoPlayTts(e.target.checked)}
                  className="rounded border-[var(--border-token)]"
                />
                Auto ▶
              </label>
            )}
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Type as the customer…"
              disabled={micBusy}
              className="flex-1 rounded-md border border-[var(--border-token)] bg-surface-card px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-primary/30 disabled:opacity-50"
            />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                void holdStart();
              }}
              onMouseUp={() => void holdEnd()}
              onMouseLeave={() => {
                if (recording) void holdEnd();
              }}
              onTouchStart={(e) => {
                e.preventDefault();
                void holdStart();
              }}
              onTouchEnd={() => void holdEnd()}
              disabled={micBusy}
              className={cn(
                "grid h-9 w-9 place-items-center rounded-full border transition disabled:opacity-50",
                recording
                  ? "border-red-400 bg-red-50 text-red-600 animate-pulse"
                  : "border-[var(--border-token)] bg-surface-card text-text-secondary hover:bg-surface-sunken",
              )}
              title="Hold to speak — Azure Speech STT"
            >
              {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={send}
              disabled={!draft.trim() || micBusy}
              className="inline-flex items-center gap-1 rounded-md bg-brand-primary px-3 py-2 text-[12.5px] font-medium text-white hover:bg-brand-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" /> Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

async function playBotText(text: string, voice: VoiceConfig): Promise<void> {
  const result = await previewTts({
    text: text.slice(0, 500),
    voiceId: voice.voiceId,
    speed: voice.speed,
    pitch: voice.pitch,
    warmth: voice.warmth,
    pauseMs: voice.pauseMs,
  });
  const url = URL.createObjectURL(result.blob);
  try {
    const audio = new Audio(url);
    await audio.play();
    await new Promise<void>((resolve) => {
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function TurnBubble({ turn, voice }: { turn: SandboxTurn; voice?: VoiceConfig | null }) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);

  if (turn.role === "system") {
    return (
      <div className="my-1 self-center rounded-full bg-surface-sunken px-3 py-1 text-[11px] text-text-muted">
        {turn.text}
      </div>
    );
  }

  const isBot = turn.role === "bot";
  const chunks: SandboxChunkHit[] = turn.chunks ?? [];
  const grounded = chunks.filter((c) => c.docTitle || c.chunkId);

  const onPlay = async () => {
    if (!voice || playing) return;
    setPlaying(true);
    try {
      await playBotText(turn.text, voice);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "TTS failed");
    } finally {
      setPlaying(false);
    }
  };

  return (
    <div className={cn("flex", isBot ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-3 py-2 text-[13px] leading-relaxed shadow-sm",
          isBot
            ? "rounded-bl-sm bg-surface-card text-text-primary"
            : "rounded-br-sm bg-brand-primary text-white",
        )}
      >
        <div>{turn.text}</div>
        {isBot && grounded.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {grounded.slice(0, 4).map((c) => (
              <span
                key={c.chunkId}
                title={c.snippet ?? c.heading ?? undefined}
                className="rounded-full border border-[var(--border-token)] bg-surface-sunken px-1.5 py-0.5 text-[10px] font-medium text-text-secondary"
              >
                grounded in {groundedLabel(c)}
              </span>
            ))}
          </div>
        )}
        {isBot && (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {voice && (
              <button
                type="button"
                onClick={() => void onPlay()}
                disabled={playing}
                className="inline-flex items-center gap-1 text-[10.5px] text-brand-primary hover:text-brand-primary-dark disabled:opacity-50"
                title="Hear this turn (Azure TTS)"
              >
                <Volume2 className="h-3 w-3" />
                {playing ? "Playing…" : "Play"}
              </button>
            )}
            {(turn.chunkIds?.length || turn.latencyMs) ? (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="inline-flex items-center gap-1 text-[10.5px] text-text-muted hover:text-text-secondary"
              >
                {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                {turn.latencyMs}ms · {turn.tokens}t · {turn.chunkIds?.length ?? 0} chunks
                {turn.guardrailFlags?.length ? ` · ⚑ ${turn.guardrailFlags.join(",")}` : ""}
              </button>
            ) : null}
          </div>
        )}
        {open && isBot && turn.chunkIds && turn.chunkIds.length > 0 && (
          <div className="mt-1.5 space-y-0.5 border-t border-[var(--border-token)] pt-1.5 font-mono text-[10.5px] text-text-muted">
            {turn.chunkIds.map((id) => (
              <div key={id}>· {id}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
