import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

describe("360 place-call and outreach", () => {
  it("places calls through the dial owner with an idempotency key", () => {
    const src = readFileSync(join(here, "outbound.ts"), "utf8");
    expect(src).toContain('objective: "manual_outbound"');
    expect(src).toContain("Idempotency-Key");
    expect(src).not.toContain("/demo/outbound-call");
  });

  it("sends 360 outreach with an idempotency key", () => {
    const src = readFileSync(join(here, "customers.ts"), "utf8");
    expect(src).toContain("/outreach");
    expect(src).toContain("Idempotency-Key");
  });
});
