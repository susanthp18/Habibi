import { describe, expect, it } from "vitest";

import { actorLabel, parseLogTimestamp } from "./change-log-actions";

describe("actorLabel", () => {
  it("calls a missing person the platform", () => {
    expect(actorLabel(null)).toBe("platform");
    expect(actorLabel(undefined)).toBe("platform");
    expect(actorLabel("")).toBe("platform");
    expect(actorLabel("  ")).toBe("platform");
  });

  it("keeps a real user id", () => {
    expect(actorLabel("priya-nair")).toBe("priya-nair");
  });
});

describe("parseLogTimestamp", () => {
  it("accepts the space Postgres str(datetime) used to send", () => {
    const d = parseLogTimestamp("2026-09-01 10:00:00+00:00");
    expect(d).not.toBeNull();
    expect(d!.getUTCDate()).toBe(1);
    expect(d!.getUTCMonth()).toBe(8);
  });
});
