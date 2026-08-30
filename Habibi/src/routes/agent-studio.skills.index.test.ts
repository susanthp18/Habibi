import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

describe("skill clone", () => {
  it("asks for the slug in an AlertDialog, not window.prompt", () => {
    const src = readFileSync(join(here, "agent-studio.skills.index.tsx"), "utf8");
    expect(src).not.toContain("window.prompt");
    expect(src).toContain("clonePending");
    expect(src).toContain("AlertDialog");
  });
});
