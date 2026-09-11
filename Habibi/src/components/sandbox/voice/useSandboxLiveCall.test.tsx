// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// End pressed during the handshake must not leave a live client behind.
//
// start() awaits the backend session, the dynamic transport import, device
// init and connect, re-checking a generation counter after each. Only start()
// itself bumped that counter, so end() during any of those awaits let the
// in-flight start() carry on: the client connected, the mic went hot, and the
// panel said "ended". end() now invalidates the generation.
// -----------------------------------------------------------------------------
import "@/test/jsdom";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const connect = vi.fn(async () => undefined);
const disconnect = vi.fn(async () => undefined);
let releaseStart: () => void = () => undefined;

vi.mock("@/api/voice-sandbox", () => ({
  startVoiceSandbox: () =>
    new Promise((resolve) => {
      releaseStart = () => resolve({ sessionId: "vs-1", webrtcUrl: "http://x/offer" });
    }),
  stopVoiceSandbox: vi.fn(async () => undefined),
  pushVoiceTune: vi.fn(async () => undefined),
}));
vi.mock("@pipecat-ai/client-js", () => ({
  PipecatClient: class {
    on() {}
    initDevices = vi.fn(async () => undefined);
    connect = connect;
    disconnect = disconnect;
    enableMic() {}
  },
  RTVIEvent: new Proxy({}, { get: (_t, k) => String(k) }),
}));
vi.mock("@pipecat-ai/small-webrtc-transport", () => ({ SmallWebRTCTransport: class {} }));

import { useSandboxLiveCall } from "./useSandboxLiveCall";

const args = {
  enabled: true,
  promptVersionId: "pv-1",
  kbSnapshotId: null,
  scenarioId: "sc-1",
  persona: {} as never,
  tuning: { tts: { voice: "v" } } as never,
  onTurns: () => undefined,
  onMetrics: () => undefined,
};

afterEach(() => vi.clearAllMocks());

describe("useSandboxLiveCall end() during the handshake", () => {
  it("does not connect after End was pressed", async () => {
    const { result } = renderHook(() => useSandboxLiveCall(args));

    act(() => {
      result.current.chrome.onStart();
    });
    // The backend session is still being created when End is pressed.
    await act(async () => {
      result.current.chrome.onEnd();
      await Promise.resolve();
    });
    await act(async () => {
      releaseStart();
      // Let the in-flight start() run past every await it has left.
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(connect).not.toHaveBeenCalled();
    expect(result.current.chrome.status).toBe("ended");
  });
});
