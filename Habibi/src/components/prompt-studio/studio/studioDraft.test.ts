import { describe, expect, it } from "vitest";

import { hydrationStart, studioHydrationBlocked, versionHasAuthoring } from "./studioDraft";
import type { PromptVersion } from "@/api/types/prompt-studio";
import { DEFAULT_GUARDRAILS, DEFAULT_PERSONA, DEFAULT_VOICE } from "@/lib/prompt-studio";

function row(over: Partial<PromptVersion> & Pick<PromptVersion, "id" | "status">): PromptVersion {
  return {
    label: over.label ?? over.id,
    author: "test",
    createdAt: "2026-09-16T00:00:00Z",
    summary: over.summary ?? "",
    prompt: over.prompt ?? "",
    persona: DEFAULT_PERSONA,
    voice: DEFAULT_VOICE,
    guardrails: DEFAULT_GUARDRAILS,
    ...over,
  };
}

describe("studioHydrationBlocked", () => {
  it("waits for the card read", () => {
    expect(
      studioHydrationBlocked({ cardPending: true, historyReady: true, hydrated: false }),
    ).toBe(true);
  });

  it("waits for the version list so an empty first paint cannot stick", () => {
    expect(
      studioHydrationBlocked({ cardPending: false, historyReady: false, hydrated: false }),
    ).toBe(true);
  });

  it("does not rehydrate after the editor already adopted a version", () => {
    expect(
      studioHydrationBlocked({ cardPending: false, historyReady: true, hydrated: true }),
    ).toBe(true);
  });

  it("allows the first adopt once both reads have settled", () => {
    expect(
      studioHydrationBlocked({ cardPending: false, historyReady: true, hydrated: false }),
    ).toBe(false);
  });
});

describe("hydrationStart", () => {
  const published = row({
    id: "v1_6",
    status: "published",
    prompt: "You are Kaia.",
    flow: { version: 1, globalTools: [], nodes: [{ id: "start" } as never], edges: [] },
  });
  const blankDraft = row({
    id: "v1_7",
    status: "draft",
    summary: "draft autosave",
    prompt: "",
    flow: {} as never,
  });
  const authoredDraft = row({
    id: "v1_7-work",
    status: "draft",
    prompt: "WIP prompt",
  });

  it("skips a blank autosave draft and opens the published prompt", () => {
    expect(versionHasAuthoring(blankDraft)).toBe(false);
    expect(hydrationStart([blankDraft, published])?.id).toBe("v1_6");
  });

  it("resumes a draft that actually has authoring", () => {
    expect(hydrationStart([authoredDraft, published])?.id).toBe("v1_7-work");
  });
});
