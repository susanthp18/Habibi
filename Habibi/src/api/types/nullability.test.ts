// -----------------------------------------------------------------------------
// WP-048 (second half): pin the wire types against schemas.py nullability.
// vitest is environment: "node" — a source pin, the same shape as WP-047.
//
// InteractionResponse.summary / CallResponse.summary / CustomerResponse
// minimumDue and lastContact are str|float | None. The first half of WP-048
// moved the types out of the seed files and left `string` / `number` in
// place. tsc is green only if those fields stay `T | null`.
// -----------------------------------------------------------------------------

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

describe("CustomerResponse nullability", () => {
  const types = read("api/types/customer360.ts");

  it("types Interaction.summary, disposition, and startedAt as string | null", () => {
    expect(types).toContain("startedAt: string | null;");
    expect(types).toContain("disposition: string | null;");
    expect(types).toContain("summary: string | null;");
    expect(types).not.toMatch(/export interface Interaction \{[\s\S]*?summary: string;/);
  });

  it("types Customer.minimumDue and lastContact as nullable", () => {
    expect(types).toContain("minimumDue: number | null;");
    expect(types).toContain("lastContact: string | null;");
  });

  it("types AccountFacts nullable fields the way AccountResponse declares them", () => {
    expect(types).toContain("openedOn: string | null;");
    expect(types).toContain("apr: number | null;");
    expect(types).toContain("sanctionedAmount: number | null;");
    expect(types).toContain("bucket: string | null;");
    expect(types).toContain("riskScore: number | null;");
  });
});

describe("CallResponse nullability", () => {
  const types = read("api/types/audit.ts");

  it("types CallRecord.summary, disposition, and startedAt as nullable", () => {
    expect(types).toContain("startedAt: string | null;");
    expect(types).toContain("disposition: Disposition | null;");
    expect(types).toContain("summary: string | null;");
  });
});

describe("POST /interactions response", () => {
  it("parses CallResponse.startedAt / disposition / summary as nullable", () => {
    const src = read("api/customers.ts");
    const callSchema = src.slice(src.indexOf("const callSchema = z.object({"));
    expect(callSchema).toContain("startedAt: z.string().nullable(),");
    expect(callSchema).toContain("disposition: z.string().nullable(),");
    expect(callSchema).toContain("summary: z.string().nullable(),");
  });
});
