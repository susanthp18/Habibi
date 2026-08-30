import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  ChevronDown,
  ChevronRight,
  Flag,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Play,
  Send,
  SkipForward,
  Volume2,
} from "lucide-react";
import { Lozenge } from "@/components/ui/lozenge";
import { groundedLabel, groundedSources, type SandboxChunkHit } from "@/api/sandbox";
import { previewTts } from "@/api/prompt-studio";
import { transcribeAudio } from "@/api/speech";
import type { VoiceConfig } from "@/data/prompt-studio-seed";
import { INTENT_LABEL, type IntentKey, type SandboxTurn } from "@/data/sandbox-seed";
import { cn } from "@/lib/utils";
import { Waveform } from "@/components/floor/Waveform";
import type { HandoffStatusEvent, LifecycleEvent } from "./voice/liveEvents";
import type { SandboxMode } from "./SandboxHeader";

export type LiveCallChrome = {
  status: "idle" | "connecting" | "live" | "ended";
  muted: boolean;
  elapsedSec: number;
  voiceLabel?: string;
  /** Last Flows nodes for the breadcrumb (server truth). */
  flowNodeHistory?: string[];
  /** Server-side speaking state — do not blend with local mic mute. */
  botSpeaking?: boolean;
  userSpeaking?: boolean;
  handoff?: HandoffStatusEvent | null;
  lifecycle?: LifecycleEvent | null;
  onStart: () => void;
  onEnd: () => void;
  onToggleMute: () => void;
};

function handoffBannerCopy(h: HandoffStatusEvent): string {
  const reason = (h.reason || "").trim() || "no reason given";
  const who = (h.assignee || h.team || "").trim();
  const whoSuffix = who ? ` · ${who}` : "";
  // `callback_queue` must not read as a live transfer.
  if (h.mode === "callback_queue") {
    return `Human callback queued — ${reason}${whoSuffix}`;
  }
  return `Handoff (${h.mode}) — ${reason}${whoSuffix}`;
}

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
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length, awaiting]);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      mediaRecorderRef.current = null;
      // Auto-played TTS outlived the panel otherwise — the clip kept talking
      // over whatever screen the user navigated to.
      const audio = activeAudioRef.current;
      if (audio) {
        audio.pause();
        audio.src = "";
        activeAudioRef.current = null;
      }
    };
  }, []);

  // Auto-play newest bot turn in text mode when enabled.
  useEffect(() => {
    if (!autoPlayTts || mode !== "text" || !voice) return;
    const lastBot = [...turns].reverse().find((t) => t.role === "bot" && t.text.trim());
    if (!lastBot || lastBot.id === lastSpokenBotId.current) return;
    if (lastBot.latencyMs === 0 && (lastBot.tokens ?? 0) === 0) return; // skip template opening
    lastSpokenBotId.current = lastBot.id;
    void playBotText(lastBot.text, voice, (audio) => {
      activeAudioRef.current = audio;
    }).catch(() => undefined);
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
      wantRecordingRef.current = false;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
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
      let settled = false;
      const finish = (value: Blob) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      const timeoutId = window.setTimeout(() => {
        finish(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
      }, 3000);
      recorder.onerror = () => {
        window.clearTimeout(timeoutId);
        finish(new Blob([], { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.onstop = () => {
        window.clearTimeout(timeoutId);
        finish(new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.stop();
    });

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    mediaRecorderRef.current = null;
    chunksRef.current = [];

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
        <div className="shrink-0 border-b border-border bg-surface">
          <div className="flex items-center gap-100 px-200 py-100">
            <Lozenge
              tone={
                live.status === "live"
                  ? "success"
                  : live.status === "connecting"
                    ? "warning"
                    : "neutral"
              }
              className="capitalize"
            >
              {live.status}
            </Lozenge>
            {(live.status === "live" || live.status === "connecting") && (
              <>
                <span className="font-mono text-body-small text-text-subtlest">
                  {formatElapsed(live.elapsedSec)}
                </span>
                <span
                  className="inline-flex items-center gap-075"
                  title="Server speaking state (bot · user)"
                  aria-label="Speaking indicator"
                >
                  <span
                    className={cn(
                      "h-100 w-100 rounded-full transition-colors",
                      live.botSpeaking
                        ? "bg-background-brand-bold"
                        : "bg-surface-sunken ring-1 ring-border",
                    )}
                  />
                  <span
                    className={cn(
                      "h-100 w-100 rounded-full transition-colors",
                      live.userSpeaking
                        ? "bg-background-success-bold"
                        : "bg-surface-sunken ring-1 ring-border",
                    )}
                  />
                  <Waveform
                    active={Boolean(live.botSpeaking || live.userSpeaking)}
                    bars={14}
                    className="ml-025 h-3.5"
                  />
                </span>
              </>
            )}
            {live.lifecycle?.phase && (
              <Lozenge
                tone="neutral"
                className="capitalize"
                title={live.lifecycle.reason || live.lifecycle.phase}
              >
                {live.lifecycle.phase}
                {live.lifecycle.phase === "idle" && live.lifecycle.reason
                  ? ` · ${live.lifecycle.reason}`
                  : ""}
              </Lozenge>
            )}
            {live.voiceLabel && (
              <span className="text-body-small text-text-subtlest">Voice: {live.voiceLabel}</span>
            )}
            {(live.flowNodeHistory?.length ?? 0) > 0 && (
              <span
                className="hidden min-w-0 truncate font-mono text-body-small text-text-subtlest sm:inline"
                title={live.flowNodeHistory!.join(" → ")}
              >
                {live.flowNodeHistory!.slice(-3).join(" → ")}
              </span>
            )}
            <div className="ml-auto flex items-center gap-075">
              {live.status === "idle" || live.status === "ended" ? (
                <button
                  type="button"
                  onClick={live.onStart}
                  className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-075 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed"
                >
                  <Phone className="h-3.5 w-3.5" /> Start call
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={live.onToggleMute}
                    className="rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken"
                  >
                    {live.muted ? "Unmute" : "Mute"}
                  </button>
                  <button
                    type="button"
                    onClick={live.onEnd}
                    className="inline-flex items-center gap-050 rounded-medium border border-border-danger-subtle bg-background-danger-subtler px-150 py-075 text-body-small font-medium text-text-danger-bolder hover:bg-background-danger-subtler"
                  >
                    <PhoneOff className="h-3.5 w-3.5" /> End
                  </button>
                </>
              )}
            </div>
          </div>
          {live.handoff && (
            <div className="border-t border-border-warning-subtle bg-background-warning-subtler px-200 py-075 text-body-small text-text-warning-bolder">
              {handoffBannerCopy(live.handoff)}
            </div>
          )}
        </div>
      )}

      {mode === "text" && lastCustomer?.intent && lastExpectedIntent && (
        <div className="flex shrink-0 items-center gap-100 border-b border-border bg-surface-sunken/60 px-200 py-075 text-body-small">
          <span className="text-text-subtlest">Scorecard</span>
          <Lozenge tone="neutral">expected {INTENT_LABEL[lastExpectedIntent]}</Lozenge>
          <Lozenge tone={lastCustomer.intent === lastExpectedIntent ? "success" : "warning"}>
            got {INTENT_LABEL[lastCustomer.intent as IntentKey] ?? lastCustomer.intent}
            {lastCustomer.intent === lastExpectedIntent ? " · match" : " · mismatch"}
          </Lozenge>
        </div>
      )}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-200 py-200">
        <div className="mx-auto flex max-w-3xl flex-col gap-100">
          {turns.map((t) => (
            <TurnBubble key={t.id} turn={t} voice={mode === "text" ? voice : null} />
          ))}
          {awaiting && (
            <Lozenge tone="neutral" className="self-start">
              <span className="flex gap-025">
                <span className="h-1.5 w-1.5 typing-dot rounded-full bg-background-brand-bold [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 typing-dot rounded-full bg-background-brand-bold [animation-delay:120ms]" />
                <span className="h-1.5 w-1.5 typing-dot rounded-full bg-background-brand-bold [animation-delay:240ms]" />
              </span>
              bot is thinking… (retrieve + chat)
            </Lozenge>
          )}
          {transcribing && (
            <Lozenge tone="neutral" className="self-end">
              Transcribing…
            </Lozenge>
          )}
        </div>
      </div>

      {mode === "text" && (
        <div className="shrink-0 border-t border-border bg-surface px-200 py-150">
          <div className="mx-auto flex max-w-3xl items-center gap-100">
            <button
              type="button"
              onClick={onPlayNext}
              disabled={!canPlayNext || micBusy}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-075 text-body-small hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
              title="Play next scripted customer turn (spends tokens)"
            >
              <Play className="h-3.5 w-3.5" /> Next
            </button>
            <button
              type="button"
              onClick={onSkipEnd}
              disabled={!canPlayNext || micBusy}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-100 py-075 text-body-small hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50"
              title="Play up to 3 remaining scripted turns"
            >
              <SkipForward className="h-3.5 w-3.5" /> Skip
            </button>
            {onAutoPlayTts && (
              <label className="inline-flex items-center gap-050 text-body-small text-text-subtlest">
                <input
                  type="checkbox"
                  checked={autoPlayTts}
                  onChange={(e) => onAutoPlayTts(e.target.checked)}
                  className="rounded border-border"
                />
                <span className="inline-flex items-center gap-025">
                  Auto <Play aria-hidden="true" className="size-3" />
                </span>
              </label>
            )}
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Type as the customer…"
              disabled={micBusy}
              className="flex-1 rounded-medium border border-border bg-surface px-150 py-100 text-body focus:outline-none focus:ring-2 focus:ring-border-brand/30 disabled:opacity-50"
            />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                void holdStart();
              }}
              onMouseUp={() => void holdEnd()}
              onMouseLeave={() => void holdEnd()}
              onPointerUp={() => void holdEnd()}
              onPointerCancel={() => void holdEnd()}
              onTouchStart={(e) => {
                e.preventDefault();
                void holdStart();
              }}
              onTouchEnd={() => void holdEnd()}
              disabled={micBusy}
              className={cn(
                "grid h-9 w-9 place-items-center rounded-full border transition disabled:opacity-50",
                recording
                  ? "border-border-danger bg-background-danger-subtler text-text-danger animate-pulse"
                  : "border-border bg-surface text-text-subtle hover:bg-surface-sunken",
              )}
              title="Hold to speak — Azure Speech STT"
            >
              {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            </button>
            <button
              type="button"
              onClick={send}
              disabled={!draft.trim() || micBusy}
              className="inline-flex items-center gap-050 rounded-medium bg-background-brand-bold px-150 py-100 text-body-small font-medium text-white hover:bg-background-brand-bold-pressed disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Send className="h-3.5 w-3.5" /> Send
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

async function playBotText(
  text: string,
  voice: VoiceConfig,
  onAudio?: (audio: HTMLAudioElement) => void,
): Promise<void> {
  const result = await previewTts({
    text: text.slice(0, 500),
    voiceId: voice.voiceId,
    shortName: voice.azureVoiceName,
    azureVoiceName: voice.azureVoiceName,
    speed: voice.speed,
    pitch: voice.pitch,
    warmth: voice.warmth,
    pauseMs: voice.pauseMs,
    style: voice.style,
  });
  const url = URL.createObjectURL(result.blob);
  try {
    const audio = new Audio(url);
    // Handed to the caller so an unmount can stop playback: without it, the
    // clip kept playing after the user navigated away from the sandbox.
    onAudio?.(audio);
    await new Promise<void>((resolve) => {
      if (audio.ended) {
        resolve();
        return;
      }
      audio.onended = () => resolve();
      audio.onerror = () => resolve();
      void audio.play().catch(() => resolve());
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function TurnBubble({ turn, voice }: { turn: SandboxTurn; voice?: VoiceConfig | null }) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        audio.src = "";
        audioRef.current = null;
      }
    };
  }, []);

  if (turn.role === "system") {
    return (
      <Lozenge tone="neutral" className="my-050 self-center">
        {turn.text}
      </Lozenge>
    );
  }

  const isBot = turn.role === "bot";
  // ONE list backs the chips, the "N chunks" counter and the expanded id list —
  // they used to read two different fields and could contradict each other.
  const grounded: SandboxChunkHit[] = groundedSources(turn);

  const onPlay = async () => {
    if (!voice || playing) return;
    setPlaying(true);
    try {
      await playBotText(turn.text, voice, (audio) => {
        audioRef.current = audio;
      });
    } catch (err) {
      if (mountedRef.current) toast.error(err instanceof Error ? err.message : "TTS failed");
    } finally {
      // The bubble can unmount mid-clip (turn list re-rendered, route change);
      // setState on an unmounted component is a no-op warning at best.
      if (mountedRef.current) setPlaying(false);
    }
  };

  return (
    <div className={cn("flex", isBot ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "max-w-[80%] rounded-xxlarge px-150 py-100 text-body leading-relaxed",
          isBot
            ? "rounded-bl-sm bg-surface text-text"
            : "rounded-br-sm bg-background-brand-bold text-white",
        )}
      >
        <div>{turn.text}</div>
        {isBot && grounded.length > 0 && (
          <div className="mt-075 flex flex-wrap gap-050">
            {grounded.map((c) => (
              <Lozenge key={c.chunkId} title={c.snippet ?? c.heading ?? undefined} tone="neutral">
                grounded in {groundedLabel(c)}
              </Lozenge>
            ))}
          </div>
        )}
        {isBot && (
          <div className="mt-050 flex flex-wrap items-center gap-100">
            {voice && (
              <button
                type="button"
                onClick={() => void onPlay()}
                disabled={playing}
                className="inline-flex items-center gap-050 text-body-small text-text-brand hover:text-text-brand disabled:opacity-50"
                title="Hear this turn (Azure TTS)"
              >
                <Volume2 className="h-3 w-3" />
                {playing ? "Playing…" : "Play"}
              </button>
            )}
            {grounded.length || turn.latencyMs ? (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="inline-flex items-center gap-050 text-body-small text-text-subtlest hover:text-text-subtle"
              >
                {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                {turn.latencyMs}ms · {turn.tokens}t · {grounded.length} chunks
                {turn.guardrailFlags?.length ? (
                  <span className="inline-flex items-center gap-025">
                    · <Flag aria-hidden="true" className="size-3" /> {turn.guardrailFlags.join(",")}
                  </span>
                ) : null}
              </button>
            ) : null}
          </div>
        )}
        {open && isBot && grounded.length > 0 && (
          <div className="mt-075 space-y-025 border-t border-border pt-075 font-mono text-body-small text-text-subtlest">
            {grounded.map((c) => (
              <div key={c.chunkId}>· {c.chunkId}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
