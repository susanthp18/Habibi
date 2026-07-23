import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  pushVoiceTune,
  startVoiceSandbox,
  stopVoiceSandbox,
} from "@/api/voice-sandbox";
import type { AgentTuning } from "@/data/agent-tuning";
import type { Persona } from "@/data/sandbox-seed";
import type { SandboxTurn } from "@/data/sandbox-seed";
import type { LiveCallChrome } from "@/components/sandbox/ConversationPanel";
import type { TurnMetric } from "@/components/sandbox/inspector/MetricsTab";

function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

/** RTVI metrics: value is seconds for ttfb/ttfa/processing; characters are counts. */
type RtviMetricPoint = {
  processor?: string;
  model?: string;
  value?: number;
};

type RtviMetricsData = {
  processing?: RtviMetricPoint[];
  ttfb?: RtviMetricPoint[];
  ttfa?: RtviMetricPoint[];
  characters?: RtviMetricPoint[];
  tokens?: Array<{
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  }>;
};

type BotOutputData = {
  text?: string;
  spoken_status?: "new" | "in-progress" | "completed" | string;
  segment_id?: number;
};

function secsToMs(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v * 1000 : null;
}

function mapRtviMetrics(data: unknown): TurnMetric[] {
  if (!data || typeof data !== "object") return [];
  const m = data as RtviMetricsData;
  const byProc = new Map<string, TurnMetric>();

  const ensure = (processor: string): TurnMetric => {
    let row = byProc.get(processor);
    if (!row) {
      row = {
        id: `${processor}-${Date.now()}-${byProc.size}`,
        label: processor,
        ttfbMs: null,
        ttfaMs: null,
        tokens: null,
        chars: null,
      };
      byProc.set(processor, row);
    }
    return row;
  };

  for (const p of m.ttfb ?? []) {
    if (!p?.processor) continue;
    ensure(p.processor).ttfbMs = secsToMs(p.value);
  }
  for (const p of m.ttfa ?? []) {
    if (!p?.processor) continue;
    ensure(p.processor).ttfaMs = secsToMs(p.value);
  }
  for (const p of m.characters ?? []) {
    if (!p?.processor) continue;
    ensure(p.processor).chars = typeof p.value === "number" ? p.value : null;
  }

  // Token rows lack processor — attach to first LLM-ish row or a synthetic one.
  const tokenRows = m.tokens ?? [];
  if (tokenRows.length) {
    const total = tokenRows.reduce(
      (sum, t) => sum + (t.total_tokens ?? (t.prompt_tokens ?? 0) + (t.completion_tokens ?? 0)),
      0,
    );
    const llmRow =
      [...byProc.values()].find((r) => /llm|openai|azure/i.test(r.label)) ??
      ensure("LLM");
    llmRow.tokens = total;
  }

  return [...byProc.values()];
}

type Args = {
  enabled: boolean;
  promptVersionId: string;
  kbSnapshotId: string | null;
  scenarioId: string;
  persona: Persona;
  tuning: AgentTuning;
  onTurns: (updater: (prev: SandboxTurn[]) => SandboxTurn[]) => void;
  onMetrics: (m: TurnMetric[]) => void;
};

export function useSandboxLiveCall(args: Args) {
  const [status, setStatus] = useState<LiveCallChrome["status"]>("idle");
  const [muted, setMuted] = useState(false);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [voiceLabel, setVoiceLabel] = useState<string | undefined>(undefined);
  const clientRef = useRef<{
    disconnect: () => Promise<void>;
    enableMic: (v: boolean) => void;
    sendClientMessage?: (type: string, data: unknown) => void;
  } | null>(null);
  const botAudioRef = useRef<HTMLAudioElement | null>(null);
  const startedAt = useRef<number | null>(null);
  const argsRef = useRef(args);
  argsRef.current = args;

  const stopBotAudio = useCallback(() => {
    const el = botAudioRef.current;
    if (!el) return;
    try {
      el.pause();
      el.srcObject = null;
      el.removeAttribute("src");
      el.load();
    } catch {
      /* ignore */
    }
    botAudioRef.current = null;
  }, []);

  const attachBotAudio = useCallback((track: MediaStreamTrack) => {
    // SmallWebRTC does not autoplay remote audio — mount it ourselves
    // (same job as <PipecatClientAudio /> in @pipecat-ai/client-react).
    let el = botAudioRef.current;
    if (!el) {
      el = new Audio();
      el.autoplay = true;
      el.setAttribute("playsinline", "true");
      botAudioRef.current = el;
    }
    el.srcObject = new MediaStream([track]);
    void el.play().catch((err) => {
      console.warn("bot audio play blocked", err);
      toast.error("Could not play bot audio", {
        description: "Click the page / allow sound, then restart the call.",
      });
    });
  }, []);

  useEffect(() => {
    if (status !== "live" && status !== "connecting") return;
    const id = window.setInterval(() => {
      if (startedAt.current) {
        setElapsedSec(Math.floor((Date.now() - startedAt.current) / 1000));
      }
    }, 500);
    return () => window.clearInterval(id);
  }, [status]);

  const end = useCallback(async () => {
    stopBotAudio();
    try {
      if (clientRef.current) {
        await clientRef.current.disconnect();
        clientRef.current = null;
      }
    } catch {
      /* ignore */
    }
    if (sessionId) {
      try {
        await stopVoiceSandbox(sessionId);
      } catch {
        /* ignore */
      }
    }
    setSessionId(null);
    setStatus("ended");
    startedAt.current = null;
  }, [sessionId, stopBotAudio]);

  const start = useCallback(async () => {
    const a = argsRef.current;
    if (!a.enabled) return;
    setStatus("connecting");
    setElapsedSec(0);
    stopBotAudio();
    a.onTurns(() => [
      {
        id: makeId(),
        role: "system",
        text: "Starting live voice session…",
        ts: Date.now(),
        systemKind: "info",
      },
    ]);
    try {
      const started = await startVoiceSandbox({
        promptVersionId: a.promptVersionId,
        kbSnapshotId: a.kbSnapshotId,
        scenarioId: a.scenarioId,
        persona: a.persona as unknown as Record<string, unknown>,
        tuning: a.tuning,
      });
      setSessionId(started.sessionId);
      setVoiceLabel(a.tuning.tts.voice);

      // Dynamic import — packages optional until installed.
      const [{ PipecatClient, RTVIEvent }, { SmallWebRTCTransport }] = await Promise.all([
        import("@pipecat-ai/client-js"),
        import("@pipecat-ai/small-webrtc-transport"),
      ]);

      const client = new PipecatClient({
        transport: new SmallWebRTCTransport(),
        enableMic: true,
        enableCam: false,
      });

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const c = client as any;

      c.on(RTVIEvent.UserTranscript, (data: { text?: string; final?: boolean }) => {
        if (!data?.final || !data.text?.trim()) return;
        a.onTurns((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "customer",
            text: data.text!.trim(),
            ts: Date.now(),
          },
        ]);
      });

      c.on(RTVIEvent.BotOutput, (data: BotOutputData) => {
        const text = (data?.text || "").trim();
        if (!text) return;
        // BotOutput streams new → in-progress → completed; only commit once.
        if (data.spoken_status && data.spoken_status !== "completed") return;
        a.onTurns((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "bot" && last.text === text) return prev;
          return [
            ...prev,
            {
              id: makeId(),
              role: "bot",
              text,
              ts: Date.now(),
              chunkIds: [],
              latencyMs: 0,
              tokens: 0,
            },
          ];
        });
      });

      c.on(RTVIEvent.TrackStarted, (track: MediaStreamTrack, participant?: { local?: boolean }) => {
        if (track.kind !== "audio") return;
        // Skip local mic when the transport tags it; SmallWebRTC remote unmute
        // usually arrives without a participant (bot audio).
        if (participant?.local === true) return;
        attachBotAudio(track);
      });

      c.on(RTVIEvent.BotReady, () => {
        setStatus("live");
        startedAt.current = Date.now();
      });

      c.on(RTVIEvent.Disconnected, () => {
        stopBotAudio();
        setStatus("ended");
      });

      c.on(RTVIEvent.Metrics, (data: unknown) => {
        try {
          const mapped = mapRtviMetrics(data);
          if (mapped.length) a.onMetrics(mapped);
        } catch {
          /* ignore */
        }
      });

      if (typeof c.initDevices === "function") {
        await c.initDevices();
      }
      await c.connect({ webrtcUrl: started.webrtcUrl });
      clientRef.current = c as typeof clientRef.current;
      setStatus("live");
      startedAt.current = Date.now();
      a.onTurns((prev) => [
        ...prev,
        {
          id: makeId(),
          role: "system",
          text: "Live call connected — speak as the customer",
          ts: Date.now(),
          systemKind: "success",
        },
      ]);
    } catch (err) {
      stopBotAudio();
      setStatus("idle");
      toast.error(err instanceof Error ? err.message : "Could not start live call", {
        description: "Install @pipecat-ai packages and run python -m voice.bot",
      });
    }
  }, [attachBotAudio, stopBotAudio]);

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m;
      try {
        clientRef.current?.enableMic(!next);
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const applyTune = useCallback(
    async (delta: Partial<AgentTuning>) => {
      if (!sessionId) return;
      try {
        // HTTP persists for restart/next-call; data channel applies mid-call.
        await pushVoiceTune(sessionId, delta);
        clientRef.current?.sendClientMessage?.("tuning_delta", delta);
      } catch {
        /* ignore */
      }
    },
    [sessionId],
  );

  const restart = useCallback(async () => {
    await end();
    await start();
  }, [end, start]);

  useEffect(() => {
    if (!args.enabled && (status === "live" || status === "connecting")) {
      void end();
    }
  }, [args.enabled, status, end]);

  useEffect(() => () => stopBotAudio(), [stopBotAudio]);

  const chrome: LiveCallChrome = {
    status,
    muted,
    elapsedSec,
    voiceLabel,
    onStart: () => void start(),
    onEnd: () => void end(),
    onToggleMute: toggleMute,
  };

  return { chrome, sessionId, applyTune, restart, status };
}
