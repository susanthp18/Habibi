// -----------------------------------------------------------------------------
// The wire contract, proved on real bodies.
//
// `generated.ts` is the API's response models rewritten as zod by
// backend/scripts/gen_wire_schemas.py; `samples.json` is one real 200 body per
// GET route, captured from the dev stack by capture_wire_samples.py. Every
// sample must resolve to a schema and parse -- a translation error in the
// generator, or a model the API does not actually honour, fails here instead
// of blanking a screen.
// -----------------------------------------------------------------------------
import { describe, expect, it } from "vitest";
import { parseWire, schemaFor, WireError } from "./index";
import samples from "./samples.json";

type Sample = { key: string; path: string; body: unknown };

describe("wire schemas", () => {
  it("resolve every sampled route", () => {
    const unresolved = (samples as Sample[])
      .filter((s) => !schemaFor("GET", s.path))
      .map((s) => s.key);
    expect(unresolved).toEqual([]);
  });

  it.each((samples as Sample[]).map((s) => [s.key, s] as const))("parse %s", (_key, s) => {
    expect(() => parseWire("GET", s.path, s.body)).not.toThrow();
  });

  it("refuse a body the model does not describe", () => {
    expect(() => parseWire("GET", "/agent-studio/cards", [{ botId: 1 }])).toThrow(WireError);
  });

  it("resolve a parameterised path to its own route, not the list beside it", () => {
    const card = schemaFor("GET", "/agent-studio/cards/kaia-v2-4?x=1");
    expect(card).toBeDefined();
    expect(card).not.toBe(schemaFor("GET", "/agent-studio/cards"));
  });
});
