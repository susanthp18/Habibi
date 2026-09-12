/**
 * `fetch` answered from the wire samples.
 *
 * `api/wire/samples.json` is one real 200 body per GET route, captured from the
 * dev stack. A route test that stubs `fetch` with them exercises the real api/
 * module -- the URL it builds, the schema it parses with, the shape it hands
 * the screen -- against bodies the server actually sent, with no request
 * library and nothing hand-written. Writes and routes the samples do not cover
 * come from `overrides`; anything else is a 404 the test will see.
 *
 * Every call is recorded, so a test can assert what a save sent.
 */
import { vi } from "vitest";

import samples from "@/api/wire/samples.json";

type Sample = { key: string; path: string; body: unknown };

export type WireCall = { method: string; path: string; search: string; body: unknown };

type Override = (call: WireCall) => unknown;

function templateToRegExp(key: string): RegExp {
  const [, template] = key.split(" ", 2);
  const source = template.replace(/[.*+?^${}()|[\]\\]/g, (c) => (c === "{" || c === "}" ? c : `\\${c}`));
  return new RegExp("^" + source.replace(/\{[^}]+\}/g, "[^/]+") + "$");
}

const SAMPLES = samples as Sample[];

function sampleFor(method: string, path: string): Sample | undefined {
  if (method !== "GET") return undefined;
  return (
    SAMPLES.find((s) => s.path === path) ??
    SAMPLES.find((s) => s.key.startsWith("GET ") && templateToRegExp(s.key).test(path))
  );
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Install the stub. `overrides` keys are `"METHOD /path"`; a path may use
 * `{param}` segments. Returns the recorded calls and a restore function.
 */
export function installWireFetch(overrides: Record<string, Override | unknown> = {}) {
  const calls: WireCall[] = [];
  const entries = Object.entries(overrides).map(([key, value]) => ({
    method: key.split(" ", 1)[0]!,
    re: templateToRegExp(key),
    value,
  }));
  const original = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    const call: WireCall = { method, path: url.pathname, search: url.search, body };
    calls.push(call);
    const hit = entries.find((e) => e.method === method && e.re.test(url.pathname));
    if (hit) {
      const value = typeof hit.value === "function" ? (hit.value as Override)(call) : hit.value;
      return value instanceof Response ? value : json(value);
    }
    const sample = sampleFor(method, url.pathname);
    if (sample) return json(sample.body);
    return json({ detail: `no sample or override for ${method} ${url.pathname}` }, 404);
  }) as typeof fetch;
  return {
    calls,
    restore: () => {
      globalThis.fetch = original;
    },
  };
}

/** The sample body for a key, for a test that wants to assert against it. */
export function sample<T = unknown>(key: string): T {
  const hit = SAMPLES.find((s) => s.key === key);
  if (!hit) throw new Error(`no wire sample for ${key}`);
  return hit.body as T;
}
