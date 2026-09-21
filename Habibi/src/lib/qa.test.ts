import { describe, expect, it } from "vitest";

import { matchQaAgent } from "./qa";

describe("matchQaAgent", () => {
  const stats = [{ agentId: "Priya Nair" }, { agentId: "intake-v1" }];

  it("matches the dashboard leaderboard name to the QA subject", () => {
    expect(matchQaAgent(stats, "Priya Nair")?.agentId).toBe("Priya Nair");
  });

  it("matches a slug from the leaderboard against a display name", () => {
    expect(matchQaAgent(stats, "priya-nair")?.agentId).toBe("Priya Nair");
  });

  it("returns undefined when the agent is missing", () => {
    expect(matchQaAgent(stats, "nobody")).toBeUndefined();
    expect(matchQaAgent(stats, "  ")).toBeUndefined();
  });
});
