// -----------------------------------------------------------------------------
// The transport's `schema` seam: every verb parses the body through the schema
// it was handed, so a wire shape the backend stopped sending fails at the
// call — not three components later as `undefined.toFixed`.
// -----------------------------------------------------------------------------

import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./config";

const rowSchema = z.object({ id: z.string(), amount: z.number() });

function respondWith(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })),
  );
}

afterEach(() => vi.unstubAllGlobals());

const verbs: Array<[string, (schema: typeof rowSchema) => Promise<unknown>]> = [
  ["apiGet", (schema) => apiGet("/rows/1", { schema })],
  ["apiPost", (schema) => apiPost("/rows", {}, { schema })],
  ["apiPatch", (schema) => apiPatch("/rows/1", {}, { schema })],
  ["apiPut", (schema) => apiPut("/rows/1", {}, { schema })],
  ["apiDelete", (schema) => apiDelete("/rows/1", { schema })],
];

describe.each(verbs)("%s with a schema", (_name, call) => {
  it("returns the parsed body when the shape is right", async () => {
    respondWith({ id: "r1", amount: 12, extra: "stripped" });
    await expect(call(rowSchema)).resolves.toEqual({ id: "r1", amount: 12 });
  });

  it("rejects a wrong shape", async () => {
    respondWith({ id: "r1", amount: "12" });
    await expect(call(rowSchema)).rejects.toBeInstanceOf(z.ZodError);
  });
});
