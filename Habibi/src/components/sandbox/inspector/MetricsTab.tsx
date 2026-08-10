import type { SandboxTurn } from "@/data/sandbox-seed";
import type {
  LiveTurnAudio,
  TurnAnalysisEvent,
} from "@/components/sandbox/voice/liveEvents";

export type TurnMetric = {
  id: string;
  label: string;
  ttfbMs?: number | null;
  ttfaMs?: number | null;
  tokens?: number | null;
  chars?: number | null;
};

function playPcmBase64(pcmBase64: string, sampleRate: number) {
  if (!pcmBase64.trim()) return;
  let raw: string;
  try {
    raw = atob(pcmBase64);
  } catch {
    return;
  }
  if (raw.length === 0 || raw.length % 2 !== 0) return;

  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);

  // Construction is inside the guard too: `sampleRate` comes from the same
  // untrusted turn payload as the audio, and an unsupported rate makes the
  // AudioContext constructor throw NotSupportedError straight out of the
  // click handler.
  let ctx: AudioContext;
  try {
    ctx = new AudioContext({ sampleRate });
  } catch {
    return;
  }
  try {
    const samples = new Int16Array(bytes.buffer);
    if (samples.length === 0) {
      void ctx.close();
      return;
    }
    const buffer = ctx.createBuffer(1, samples.length, sampleRate);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.onended = () => void ctx.close();
    src.start();
  } catch {
    void ctx.close();
  }
}

/** Stage split for one bot turn — the shape the caller actually waited through. */
const STAGES: Array<{ key: keyof TurnAnalysisEvent; label: string }> = [
  { key: "userTurnMs", label: "turn end" },
  { key: "sttTtfbMs", label: "STT" },
  { key: "toolMs", label: "tools" },
  { key: "llmTtfbMs", label: "LLM" },
  { key: "ttsTtfbMs", label: "TTS" },
];

export function MetricsTab({
  metrics,
  turns,
  turnAudio = [],
  analysis = [],
}: {
  metrics: TurnMetric[];
  turns: SandboxTurn[];
  turnAudio?: LiveTurnAudio[];
  /** Server-measured per-turn breakdown; empty in text rehearsal. */
  analysis?: TurnAnalysisEvent[];
}) {
  const botTurns = analysis.filter(
    (t) => t.speaker === "bot" && STAGES.some(({ key }) => typeof t[key] === "number"),
  );

  if (metrics.length === 0 && turnAudio.length === 0 && botTurns.length === 0) {
    return (
      <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
        Metrics appear during Live voice (TTFB / TTFA / tokens). Text mode shows latency on bot
        bubbles.
      </div>
    );
  }

  // Only text-path turns carry a real latency; live bot outputs are recorded
  // with latencyMs: 0, so exclude them or the average reads "0ms" during a call.
  const botLatencies = turns
    .filter((t) => t.role === "bot" && typeof t.latencyMs === "number" && t.latencyMs > 0)
    .map((t) => t.latencyMs as number);

  return (
    <div className="space-y-150">
      {botTurns.length > 0 && (
        <div className="space-y-075">
          <div className="text-body-small font-medium text-text-subtle">
            Per-turn latency breakdown
          </div>
          {botTurns.map((t) => {
            const total = STAGES.reduce(
              (sum, { key }) => sum + (typeof t[key] === "number" ? (t[key] as number) : 0),
              0,
            );
            return (
              <div
                key={t.turnIndex}
                className="rounded-medium border border-border bg-surface-sunken p-150"
              >
                <div className="flex items-baseline justify-between text-body-small">
                  <span className="font-medium text-text">Turn {t.turnIndex}</span>
                  <span className="font-mono text-text-subtlest">{Math.round(total)}ms</span>
                </div>
                {/* Proportional bar, not a chart: the point is which stage owns
                    the wait, and a caller feels the sum, not the pieces. */}
                <div className="mt-075 flex h-1.5 w-full overflow-hidden rounded bg-surface">
                  {STAGES.map(({ key }, i) => {
                    const v = typeof t[key] === "number" ? (t[key] as number) : 0;
                    if (!v || !total) return null;
                    return (
                      <div
                        key={key}
                        className={i % 2 ? "bg-background-brand-bold/50" : "bg-background-brand-bold"}
                        style={{ width: `${(v / total) * 100}%` }}
                      />
                    );
                  })}
                </div>
                <div className="mt-050 flex flex-wrap gap-x-150 gap-y-025 font-mono text-body-small text-text-subtlest">
                  {STAGES.map(({ key, label }) =>
                    typeof t[key] === "number" ? (
                      <span key={key}>
                        {label} {Math.round(t[key] as number)}ms
                      </span>
                    ) : null,
                  )}
                  {t.tokens != null && <span>{t.tokens} tok</span>}
                  {t.interrupted && <span className="text-text-warning-bolder">interrupted</span>}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {botLatencies.length > 0 && (
        <div className="rounded-medium border border-border bg-surface-sunken p-150 text-body-small text-text-subtle">
          Text path avg latency:{" "}
          <span className="font-mono font-medium text-text">
            {Math.round(botLatencies.reduce((a, b) => a + b, 0) / botLatencies.length)}ms
          </span>
        </div>
      )}
      {metrics.map((m) => (
        <div
          key={m.id}
          className="rounded-medium border border-border bg-surface-sunken p-150 text-body-small"
        >
          <div className="font-medium text-text">{m.label}</div>
          <div className="mt-050 grid grid-cols-2 gap-050 font-mono text-body-small text-text-subtlest">
            {m.ttfbMs != null && <span>TTFB {Math.round(m.ttfbMs)}ms</span>}
            {m.ttfaMs != null && <span>TTFA {Math.round(m.ttfaMs)}ms</span>}
            {m.tokens != null && <span>{m.tokens} tok</span>}
            {m.chars != null && <span>{m.chars} chars</span>}
          </div>
        </div>
      ))}
      {turnAudio.length > 0 && (
        <div className="space-y-075">
          <div className="text-body-small font-medium text-text-subtle">Turn audio (last clips)</div>
          {turnAudio.map((clip) => (
            <button
              key={clip.id}
              type="button"
              className="flex w-full items-center justify-between rounded-medium border border-border bg-surface-sunken px-150 py-075 text-left text-body-small hover:bg-surface-raised"
              onClick={() => playPcmBase64(clip.pcmBase64, clip.sampleRate || 16000)}
            >
              <span className="capitalize text-text">{clip.speaker} turn</span>
              <span className="font-mono text-body-small text-text-subtlest">
                {Math.round((clip.bytes / ((clip.sampleRate || 16000) * 2)) * 1000)}ms · play
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
