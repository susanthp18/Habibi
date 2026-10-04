// @vitest-environment jsdom
import "@/test/jsdom";

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { HandoffSession } from "@/api/handoff";

type Handler = (event: string, data: unknown) => void;
const stream = vi.hoisted(() => ({ handler: null as Handler | null }));

vi.mock("@/api/config", async (orig) => ({
  ...(await orig<typeof import("@/api/config")>()),
  apiEventStream: (_path: string, onEvent: Handler) => {
    stream.handler = onEvent;
    return new Promise(() => {});
  },
}));
vi.mock("@/api/wire/generated", async (orig) => ({
  ...(await orig<typeof import("@/api/wire/generated")>()),
  FloorCopilotResponse: { parse: (x: unknown) => x },
}));

const { ApiError } = await import("@/api/config");
const { pollCase, useCopilotStream } = await import("@/api/handoff");

function caseState(status: HandoffSession["status"], callState: "live" | "ended") {
  return { status, activeCall: { callState } } as HandoffSession;
}

describe("pollCase", () => {
  it("keeps reading a case wrapped up while its call is still live", () => {
    expect(pollCase(caseState("completed", "live"), null)).toBe(5_000);
  });

  it("stops once the case is closed and its call over, or access is lost", () => {
    expect(pollCase(caseState("completed", "ended"), null)).toBe(false);
    expect(
      pollCase(caseState("active", "live"), new ApiError("GET", "/handoff/x", 403, "no")),
    ).toBe(false);
    expect(pollCase(caseState("active", "ended"), null)).toBe(5_000);
  });
});

describe("useCopilotStream", () => {
  it("shows the engines' draft at once, then the polished wording", () => {
    const { result } = renderHook(() => useCopilotStream("IX-1", "ev"));
    act(() =>
      stream.handler!("pack", {
        engineDraft: "Authority: escalate.",
        vetoes: [],
        engines: { unavailable: [] },
        approvals: [],
      }),
    );
    expect(result.current.whisper).toBe("Authority: escalate.");
    act(() => stream.handler!("token", { text: "Escalate " }));
    expect(result.current.whisper).toBe("Escalate ");
    act(() => stream.handler!("token", { text: "now." }));
    expect(result.current.whisper).toBe("Escalate now.");
  });
});
