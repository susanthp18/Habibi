import { studioSocketUrl } from "@/api/studio-engine";

/**
 * A supervisor's line into a live Voice Studio call (engine
 * `integrations/supervisor`, gated and audited by PayInt's gateway).
 *
 * - `listen`: both sides of the call play here, with the live transcript.
 * - `takeover`: the same, and the microphone reaches the caller while the
 *   agent is held. `release(note)` hands the call back; `end()` hangs up.
 *
 * Audio frames arrive as `[tag u8][sampleRate u32 LE][PCM16 LE]`; the browser
 * resamples each buffer to the output device, so no DSP lives here.
 */
export type LineMode = "listen" | "takeover";
export type LineTurn = {
  speaker: "caller" | "agent" | "supervisor";
  text: string;
  final: boolean;
  /** The part of `text` that no later interim result can replace. */
  settled?: string;
};

/**
 * One running line per speaker turn. The agent's words arrive one event at a
 * time and the caller's recognition in segments, each segment as interim
 * results and then a final one: an interim replaces the previous interim, a
 * final joins what is settled.
 */
export function mergeTurn(turns: LineTurn[], t: LineTurn, keep = 40): LineTurn[] {
  const last = turns[turns.length - 1];
  if (!last || last.speaker !== t.speaker) {
    return [...turns, { ...t, settled: t.final ? t.text : "" }].slice(-keep);
  }
  const settled = last.settled ?? "";
  const text = `${settled} ${t.text}`.trim();
  return [
    ...turns.slice(0, -1),
    { speaker: t.speaker, text, final: t.final, settled: t.final ? text : settled },
  ];
}
export type LineState = {
  status: "connecting" | "live" | "closed";
  mode: LineMode;
  reason?: string;
  micError?: string;
};

/** What the Floor shows of a supervisor's line into one call. */
export type LiveLine = LineState & { callId: string; turns: LineTurn[]; talking: boolean };

const TAG_SUPERVISOR = 3;
/** Playback is kept at most this far ahead of the clock (s); later audio is dropped. */
const MAX_LEAD_S = 0.5;
const START_LEAD_S = 0.06;

const MIC_WORKLET = `
class Mic extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("supervisor-mic", Mic);
`;

export class SupervisorLine {
  talking = false;
  private ws?: WebSocket;
  private ctx?: AudioContext;
  private mic?: MediaStream;
  private playAt = new Map<number, number>();
  private closed = false;

  constructor(
    readonly mode: LineMode,
    private readonly on: { turn: (t: LineTurn) => void; state: (s: LineState) => void },
  ) {}

  async open(runId: string): Promise<void> {
    this.on.state({ status: "connecting", mode: this.mode });
    const url = await studioSocketUrl(`/api/v1/supervise/${runId}/${this.mode}`);
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (m) => {
      if (typeof m.data === "string") void this.onText(m.data);
      else this.onAudio(m.data as ArrayBuffer);
    };
    ws.onclose = (e) => {
      this.teardown();
      this.on.state({ status: "closed", mode: this.mode, reason: e.reason || undefined });
    };
  }

  /** Hand the call back to the agent, with an optional note for it. */
  release(note?: string) {
    this.send({ type: "release", note: note ?? "" });
  }

  end() {
    this.send({ type: "end" });
  }

  close() {
    this.ws?.close();
    this.teardown();
  }

  private send(message: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }

  private async onText(raw: string) {
    type LineMessage = {
      type?: string;
      payload?: { text?: string; final?: boolean };
      sampleRate?: number;
    };
    let event: LineMessage;
    try {
      event = JSON.parse(raw) as LineMessage;
    } catch {
      return;
    }
    if (event.type === "hello") {
      this.ctx = new AudioContext({ sampleRate: event.sampleRate || 8000 });
      void this.ctx.resume();
      this.on.state({ status: "live", mode: this.mode });
      if (this.mode === "takeover") await this.startMic();
    } else if (event.type === "rtf-user-transcription" && event.payload?.text) {
      this.on.turn({
        speaker: "caller",
        text: event.payload.text,
        final: event.payload.final !== false,
      });
    } else if (event.type === "rtf-bot-text" && event.payload?.text) {
      this.on.turn({ speaker: "agent", text: event.payload.text, final: true });
    }
  }

  private onAudio(buf: ArrayBuffer) {
    const ctx = this.ctx;
    if (!ctx || buf.byteLength < 7) return;
    const view = new DataView(buf);
    const tag = view.getUint8(0);
    // Your own voice is not played back to you.
    if (tag === TAG_SUPERVISOR && this.mode === "takeover") return;
    const rate = view.getUint32(1, true);
    const samples = new Int16Array(buf.slice(5, 5 + ((buf.byteLength - 5) & ~1)));
    const audio = ctx.createBuffer(1, samples.length, rate);
    const channel = audio.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i]! / 32768;
    const now = ctx.currentTime;
    let at = this.playAt.get(tag) ?? 0;
    if (at < now || at > now + MAX_LEAD_S) at = now + START_LEAD_S;
    const src = ctx.createBufferSource();
    src.buffer = audio;
    src.connect(ctx.destination);
    src.start(at);
    this.playAt.set(tag, at + audio.duration);
  }

  private async startMic() {
    const ctx = this.ctx;
    if (!ctx) return;
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const module = URL.createObjectURL(new Blob([MIC_WORKLET], { type: "text/javascript" }));
      await ctx.audioWorklet.addModule(module);
      URL.revokeObjectURL(module);
      // The context runs at the call's rate, so the browser resamples the mic to it.
      const source = ctx.createMediaStreamSource(this.mic);
      const node = new AudioWorkletNode(ctx, "supervisor-mic");
      node.port.onmessage = (m: MessageEvent<Float32Array>) => {
        if (!this.talking || this.ws?.readyState !== WebSocket.OPEN) return;
        const f = m.data;
        const pcm = new Int16Array(f.length);
        for (let i = 0; i < f.length; i++) pcm[i] = Math.max(-1, Math.min(1, f[i]!)) * 0x7fff;
        this.ws.send(pcm.buffer);
      };
      source.connect(node);
    } catch (e) {
      this.on.state({
        status: "live",
        mode: this.mode,
        micError:
          e instanceof Error && e.name === "NotAllowedError"
            ? "Microphone permission was denied"
            : "This browser cannot send your microphone to the call (use Chrome or Edge)",
      });
    }
  }

  private teardown() {
    if (this.closed) return;
    this.closed = true;
    this.mic?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
  }
}
