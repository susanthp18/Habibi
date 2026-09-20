import { describe, expect, it } from "vitest";
import { clampAgentTuning, DEFAULT_AGENT_TUNING } from "./agent-tuning";

describe("clampAgentTuning", () => {
  it("keeps always and first_speech mute strategies", () => {
    const out = clampAgentTuning({
      ...DEFAULT_AGENT_TUNING,
      interaction: {
        ...DEFAULT_AGENT_TUNING.interaction,
        mute: ["always", "first_speech"],
      },
    });
    expect(out.interaction.mute).toEqual(["always", "first_speech"]);
  });

  it("clamps completion tokens to the backend 32–1024 range", () => {
    expect(clampAgentTuning({ llm: { ...DEFAULT_AGENT_TUNING.llm, max_completion_tokens: 10 } }).llm.max_completion_tokens).toBe(32);
    expect(clampAgentTuning({ llm: { ...DEFAULT_AGENT_TUNING.llm, max_completion_tokens: 4000 } }).llm.max_completion_tokens).toBe(1024);
  });

  it("defaults idle timeout to the collections preset when missing", () => {
    expect(DEFAULT_AGENT_TUNING.interaction.idle_timeout_secs).toBe(12);
  });

  it("clamps idle timeout to 20", () => {
    expect(
      clampAgentTuning({
        interaction: { ...DEFAULT_AGENT_TUNING.interaction, idle_timeout_secs: 28 },
      }).interaction.idle_timeout_secs,
    ).toBe(20);
  });
});
