// -----------------------------------------------------------------------------
// WP-048 ratchet: live `api/` modules do not take their contract from fixtures.
//
// Two things are pinned, as text, over every non-test src/api/*.ts:
//   1. No module imports a *type* from src/data/. The wire types live in
//      src/api/types/<domain>.ts (or are inferred from a zod schema beside the
//      call); a seed file that owned the type would make the mock the contract.
//   2. The set of modules that import mock *fixtures* from src/data/ for their
//      USE_MOCK branch is exactly the list below. A new importer fails the
//      test; a cleaned-up one fails it too, so the list only ever shrinks.
// vitest is environment: "node" — a source pin, the same shape as WP-047.
// -----------------------------------------------------------------------------

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const apiDir = dirname(fileURLToPath(import.meta.url));

/** Every import / re-export statement whose source is under src/data/, multi-line included. */
const FROM_DATA =
  /^[ \t]*(?:import|export)\b[^;]*?\bfrom\s+["'](?:@\/data\/|\.\.\/data\/|\.\/data\/)[^;]*;/gm;
/** `import type { … }` or a `type X` specifier inside the braces. */
const TYPE_IMPORT = /^[ \t]*import\s+type\b|^[ \t]*import\s*\{[^}]*\btype\s+\w/;

/**
 * Modules whose USE_MOCK branch serves seed fixtures. Fixture *values*, not
 * types — and only until the mock branch itself goes. Delete an entry when its
 * module stops importing from data/; do not add one.
 */
const FIXTURE_IMPORTERS = [
  "audit.ts",
  "authority.ts",
  "billing.ts",
  "consent.ts",
  "contact-policy.ts",
  "customers.ts",
  "products.ts",
  // Held by the Studio stream while this ratchet landed; fixtures only.
  "prompt-studio.ts",
  "qa.ts",
  "redaction.ts",
  "routing.ts",
  "upsell.ts",
  "webhooks.ts",
];

/** The type-import exceptions. Empty since WP-048 closed; stays empty. */
const TYPE_IMPORTERS: string[] = [];

function apiModules(): string[] {
  return readdirSync(apiDir)
    .filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts"))
    .sort();
}

describe("src/api does not import its contract from src/data", () => {
  const dataImports = new Map<string, string[]>();
  for (const file of apiModules()) {
    const statements = [...readFileSync(join(apiDir, file), "utf8").matchAll(FROM_DATA)].map(
      (m) => m[0],
    );
    if (statements.length) dataImports.set(file, statements);
  }

  it("imports no types from data/ (outside the named exceptions)", () => {
    const offenders = [...dataImports]
      .filter(([, statements]) => statements.some((stmt) => TYPE_IMPORT.test(stmt)))
      .map(([file]) => file);
    expect(offenders).toEqual(TYPE_IMPORTERS);
  });

  it("imports fixtures from data/ only in the modules already on the list", () => {
    expect([...dataImports.keys()]).toEqual([...FIXTURE_IMPORTERS].sort());
  });
});
