import { describe, expect, it } from "vitest";

import { gateTone } from "./gate-status";

describe("gateTone", () => {
  it("never paints skipped green", () => {
    // ORG-02 / TOOLS-3 / OUTBOUND-13: six local colour maps each forgot one
    // of the two words that are neither pass nor fail.
    expect(gateTone("skipped")).toBe("neutral");
    expect(gateTone("warn")).toBe("warning");
  });

  it("knows the eval harness's words too", () => {
    expect(gateTone("error")).toBe("danger");
    expect(gateTone("partial")).toBe("warning");
    expect(gateTone("stale")).toBe("warning");
  });

  it("does not invent a verdict for a word nobody computed", () => {
    expect(gateTone("passed")).toBe("neutral");
    expect(gateTone("")).toBe("neutral");
  });
});
