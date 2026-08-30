// -----------------------------------------------------------------------------
// Data-layer configuration — the single switch between mock and live backend.
//
// Dev default: mock ON unless VITE_USE_MOCK=false.
// Production builds: mock OFF unless explicitly forced (and that throws).
// -----------------------------------------------------------------------------

const rawMock = import.meta.env.VITE_USE_MOCK;
const isProd = import.meta.env.PROD;

export const USE_MOCK = (() => {
  if (isProd) {
    // Production must talk to the live API. Explicit mock is a hard error.
    if (rawMock === "true") {
      throw new Error(
        "VITE_USE_MOCK=true is not allowed in production builds. Unset it or set false.",
      );
    }
    return false;
  }
  // Dev: default mock=true for offline UI; set VITE_USE_MOCK=false to hit API.
  return (rawMock ?? "true") !== "false";
})();

/** Base URL for the CRM backend API (used once USE_MOCK is false). */
export const API_BASE_URL = (() => {
  const raw = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (raw) return raw.replace(/\/$/, "");
  if (isProd) {
    throw new Error(
      "VITE_API_BASE_URL is required in production builds (must not default to localhost).",
    );
  }
  return "http://localhost:8000";
})();

/** Optional shared secret — must match backend API_KEY when that env is set. */
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined)?.trim() || "";

/**
 * Optional acting user id (users.id). Sent as X-Actor-User-Id when the backend
 * allows actor headers (ALLOW_ACTOR_HEADER / non-prod). Prefer per-user
 * API_KEY_MAP on the server for production attribution.
 */
const ACTOR_USER_ID = (import.meta.env.VITE_ACTOR_USER_ID as string | undefined)?.trim() || "";

const DEFAULT_TIMEOUT_MS = 30_000;

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (API_KEY) headers.set("X-API-Key", API_KEY);
  if (ACTOR_USER_ID) headers.set("X-Actor-User-Id", ACTOR_USER_ID);
  return headers;
}

function withTimeout(ms = DEFAULT_TIMEOUT_MS): AbortSignal {
  return AbortSignal.timeout(ms);
}

/**
 * Caller signal AND the default timeout, not one or the other.
 *
 * `init?.signal ?? withTimeout()` dropped the timeout entirely whenever a
 * caller passed its own signal, so any request with a cancellation token could
 * hang forever against an unresponsive backend.
 */
function requestSignal(caller?: AbortSignal, ms = DEFAULT_TIMEOUT_MS): AbortSignal {
  const timeout = withTimeout(ms);
  if (!caller) return timeout;
  // AbortSignal.any is baseline in every browser this app targets; fall back to
  // the caller's signal if an older runtime lacks it.
  return typeof AbortSignal.any === "function" ? AbortSignal.any([caller, timeout]) : caller;
}

/** Simulate network latency so loading/skeleton states are exercised in mock mode. */
export function mockDelay<T>(value: T, ms = 250): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), ms);
  });
}

/**
 * Extract an error message from a failed Response, reading the body only once.
 * `res.json()` consumes the stream, so a later `res.text()` fallback would throw
 * on a locked stream and lose a plain-text backend message — read text first,
 * then try to parse it as JSON.
 */
async function errorDetail(res: Response): Promise<string> {
  const fallback = `${res.status} ${res.statusText}`;
  let raw: string;
  try {
    raw = await res.text();
  } catch {
    return fallback;
  }
  if (!raw) return fallback;
  const clipped = raw.length > 400 ? `${raw.slice(0, 400)}…` : raw;
  try {
    const payload = JSON.parse(raw) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail.length > 400 ? `${payload.detail.slice(0, 400)}…` : payload.detail;
    }
    if (payload.detail != null) {
      const asJson = JSON.stringify(payload.detail);
      return asJson.length > 400 ? `${asJson.slice(0, 400)}…` : asJson;
    }
    return clipped;
  } catch {
    return clipped;
  }
}

/**
 * A failed HTTP response, carrying the status that produced it.
 *
 * Before this existed every helper threw a bare `Error`, which meant a caller
 * that wanted to treat "the server says this does not exist" differently from
 * "the request did not complete" had no way to ask — so callers stopped asking.
 * The result is the failure mode this codebase names as its #1: absence and
 * failure rendered identically, and always as absence. A card that IS live
 * showing "never published" during an outage; a skill detail page rendering
 * "Skill not found." on a 500; a connectors panel telling the author to go
 * approve connectors that are, in fact, already approved.
 *
 * None of those are fixable at the call site while the only thing thrown is a
 * string. So the status travels with the error, and `isNotFound` is the one
 * predicate a caller needs to write the honest version.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly path: string;

  constructor(method: string, path: string, status: number, detail: string) {
    super(`${method} ${path} failed: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

/** True only for a real 404 from the API — never for a network or 5xx failure. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/**
 * React-Query `retry` for endpoints whose 4xx answers are deterministic.
 *
 * RQ v5 retries everything three times by default, so a genuinely bad URL costs
 * ~7s of spinner before the page is allowed to say so, and a 400/422 from a
 * request that will be rejected identically every time is sent three more
 * times. Server faults are still worth retrying; a verdict is not.
 */
export function retryUnlessClientError(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    // Two 4xx codes are about timing rather than about the request, so resending
    // the identical body is exactly the right move: 408 says the server gave up
    // waiting for it, and 429 says to come back. Treating the whole 4xx range as
    // a settled verdict would make the studio give up on a rate limit it only
    // had to wait out.
    if (error.status === 408 || error.status === 429) return failureCount < 2;
    return false;
  }
  return failureCount < 2;
}

/** Thin typed GET helper for the live API. */
export async function apiGet<T>(path: string, init?: { signal?: AbortSignal }): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: authHeaders(),
    credentials: "include",
    signal: requestSignal(init?.signal),
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    throw new ApiError("GET", path, res.status, await errorDetail(res));
  }
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

async function apiSend<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  init?: { signal?: AbortSignal; headers?: Record<string, string> },
): Promise<T> {
  const headers = authHeaders(
    body !== undefined ? { "Content-Type": "application/json" } : undefined,
  );
  if (init?.headers) {
    for (const [k, v] of Object.entries(init.headers)) headers.set(k, v);
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: requestSignal(init?.signal),
  });
  if (!res.ok) {
    throw new ApiError(method, path, res.status, await errorDetail(res));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function apiPost<T>(
  path: string,
  body: unknown,
  init?: { signal?: AbortSignal; headers?: Record<string, string> },
): Promise<T> {
  return apiSend<T>("POST", path, body, init);
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiSend<T>("PATCH", path, body);
}

export function apiDelete<T = void>(path: string): Promise<T> {
  return apiSend<T>("DELETE", path);
}

/** GET that returns a binary Blob (skill zip, reports). */
export async function apiGetBlob(path: string): Promise<{ blob: Blob; headers: Headers }> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: authHeaders({ Accept: "application/zip, application/octet-stream, application/json" }),
    credentials: "include",
    signal: withTimeout(60_000),
  });
  if (!res.ok) {
    throw new ApiError("GET", path, res.status, await errorDetail(res));
  }
  return { blob: await res.blob(), headers: res.headers };
}
export async function apiPostBlob(
  path: string,
  body: unknown,
): Promise<{ blob: Blob; headers: Headers }> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: authHeaders({
      Accept: "audio/mpeg, application/json",
      "Content-Type": "application/json",
    }),
    credentials: "include",
    body: JSON.stringify(body),
    signal: withTimeout(60_000),
  });
  if (!res.ok) {
    throw new ApiError("POST", path, res.status, await errorDetail(res));
  }
  return { blob: await res.blob(), headers: res.headers };
}

/** Multipart upload helper (no Content-Type — browser sets boundary). */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: authHeaders(),
    credentials: "include",
    body: form,
    signal: withTimeout(120_000),
  });
  if (!res.ok) {
    throw new ApiError("POST", path, res.status, await errorDetail(res));
  }
  return (await res.json()) as T;
}

/** SSE GET. No default 30s timeout — the stream is the response. */
export async function apiEventStream(
  path: string,
  onEvent: (event: string, data: unknown) => void,
  init?: { signal?: AbortSignal },
): Promise<void> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: authHeaders({ Accept: "text/event-stream" }),
    credentials: "include",
    signal: init?.signal,
  });
  if (!res.ok) {
    throw new ApiError("GET", path, res.status, await errorDetail(res));
  }
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop() ?? "";
    for (const block of blocks) {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      const raw = dataLines.join("\n");
      if (!raw) continue;
      try {
        onEvent(event, JSON.parse(raw) as unknown);
      } catch {
        onEvent(event, raw);
      }
    }
  }
}
