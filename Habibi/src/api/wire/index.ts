/**
 * The wire contract, applied at the transport: every JSON the API returns is
 * parsed against the zod schema generated from that route's response model
 * (`generated.ts`, from `backend/scripts/gen_wire_schemas.py`).
 *
 * `schemaFor(method, path)` resolves a concrete request path to the route
 * template it was registered under, static routes before parameterised ones
 * in the API's own registration order -- the same order FastAPI matches in.
 * A path no route claims (a query the API does not model) parses nothing.
 */
import type { ZodTypeAny } from "zod";
import { ROUTES } from "./generated";

type Compiled = { method: string; re: RegExp; schema: ZodTypeAny; params: boolean };

const compiled: Compiled[] = ROUTES.map(([key, schema]) => {
  // Every generated key is "METHOD /path"; a key without the space is a
  // generator bug, not a runtime case.
  const [method = "", template = ""] = key.split(" ", 2);
  const source = template
    .split("/")
    .map((seg) => (seg.startsWith("{") ? "[^/]+" : seg.replace(/[.*+?^$()|[\]\\]/g, "\\$&")))
    .join("/");
  return { method, re: new RegExp(`^${source}$`), schema, params: template.includes("{") };
});

export class WireError extends Error {
  readonly method: string;
  readonly path: string;
  readonly issues: string;

  constructor(method: string, path: string, issues: string) {
    super(`${method} ${path} returned a body the API's own model does not describe: ${issues}`);
    this.name = "WireError";
    this.method = method;
    this.path = path;
    this.issues = issues;
  }
}

/** The schema of `method path`'s 200 body, or undefined when no route models it. */
export function schemaFor(method: string, path: string): ZodTypeAny | undefined {
  const bare = path.split("?", 1)[0] ?? path;
  let fallback: ZodTypeAny | undefined;
  for (const route of compiled) {
    if (route.method !== method || !route.re.test(bare)) continue;
    if (!route.params) return route.schema;
    fallback ??= route.schema;
  }
  return fallback;
}

/** Parse `payload` as the body `method path` is declared to return. */
export function parseWire<T>(method: string, path: string, payload: unknown): T {
  const schema = schemaFor(method, path);
  if (!schema) return payload as T;
  const result = schema.safeParse(payload);
  if (result.success) return result.data as T;
  const issues = result.error.issues
    .slice(0, 5)
    .map((i) => `${i.path.join(".") || "<root>"}: ${i.message}`)
    .join("; ");
  throw new WireError(method, path, issues);
}
