// -----------------------------------------------------------------------------
// WP-049: USE_MOCK is a transport switch, not a presentation-layer conditional.
// Screens that asked "are we mocked?" when the real question was "did /staff
// return rows?" rendered an empty assignee dropdown against a live empty roster.
// vitest is environment: "node" — pin the source the way WP-047/WP-050 do.
// -----------------------------------------------------------------------------

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    if (name.endsWith(".test.ts") || name.endsWith(".test.tsx")) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (name.endsWith(".ts") || name.endsWith(".tsx")) out.push(full);
  }
  return out;
}

describe("USE_MOCK stays in api/", () => {
  it("is not imported from components/ or routes/", () => {
    const hits: string[] = [];
    for (const dir of ["components", "routes"]) {
      for (const file of walk(join(srcRoot, dir))) {
        const src = readFileSync(file, "utf8");
        if (/\bUSE_MOCK\b/.test(src)) hits.push(relative(srcRoot, file).replace(/\\/g, "/"));
      }
    }
    expect(hits).toEqual([]);
  });
});
