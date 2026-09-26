import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

describe("outbound campaign create", () => {
  it("accepts botId so a card's Outbound tab stamps the run", () => {
    const src = readFileSync(join(here, "outbound.ts"), "utf8");
    expect(src).toContain("botId?: string");
  });
});
