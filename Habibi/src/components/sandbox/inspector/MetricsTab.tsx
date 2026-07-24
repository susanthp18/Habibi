import type { SandboxTurn } from "@/data/sandbox-seed";
import type { LiveTurnAudio } from "@/components/sandbox/voice/liveEvents";

export type TurnMetric = {
  id: string;
  label: string;
  ttfbMs?: number | null;
  ttfaMs?: number | null;
  tokens?: number | null;
  chars?: number | null;
};

function playPcmBase64(pcmBase64: string, sampleRate: number) {
  const raw = atob(pcmBase64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const samples = new Int16Array(bytes.buffer);
  const ctx = new AudioContext({ sampleRate });
  const buffer = ctx.createBuffer(1, samples.length, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);
  src.start();
  src.onended = () => void ctx.close();
}

export function MetricsTab({
  metrics,
  turns,
  turnAudio = [],
}: {
  metrics: TurnMetric[];
  turns: SandboxTurn[];
  turnAudio?: LiveTurnAudio[];
}) {
  if (metrics.length === 0 && turnAudio.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
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
    <div className="space-y-3">
      {botLatencies.length > 0 && (
        <div className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5 text-[11px] text-text-secondary">
          Text path avg latency:{" "}
          <span className="font-mono font-medium text-text-primary">
            {Math.round(botLatencies.reduce((a, b) => a + b, 0) / botLatencies.length)}ms
          </span>
        </div>
      )}
      {metrics.map((m) => (
        <div
          key={m.id}
          className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5 text-[11.5px]"
        >
          <div className="font-medium text-text-primary">{m.label}</div>
          <div className="mt-1 grid grid-cols-2 gap-1 font-mono text-[10.5px] text-text-muted">
            {m.ttfbMs != null && <span>TTFB {Math.round(m.ttfbMs)}ms</span>}
            {m.ttfaMs != null && <span>TTFA {Math.round(m.ttfaMs)}ms</span>}
            {m.tokens != null && <span>{m.tokens} tok</span>}
            {m.chars != null && <span>{m.chars} chars</span>}
          </div>
        </div>
      ))}
      {turnAudio.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium text-text-secondary">Turn audio (last clips)</div>
          {turnAudio.map((clip) => (
            <button
              key={clip.id}
              type="button"
              className="flex w-full items-center justify-between rounded-md border border-[var(--border-token)] bg-surface-sunken px-2.5 py-1.5 text-left text-[11px] hover:bg-surface-raised"
              onClick={() => playPcmBase64(clip.pcmBase64, clip.sampleRate || 16000)}
            >
              <span className="capitalize text-text-primary">{clip.speaker} turn</span>
              <span className="font-mono text-[10px] text-text-muted">
                {Math.round(clip.bytes / 32)}ms · play
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
