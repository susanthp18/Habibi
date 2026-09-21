// -----------------------------------------------------------------------------
// Data-layer configuration -- where the API is and how a request is made.
//
// Screens never import this module; they consume the domain api/ module's
// hooks and functions (enforced by eslint's no-restricted-imports).
// -----------------------------------------------------------------------------

import { getAccessToken, entraConfigured } from "@/lib/sso";
import { parseWire } from "./wire";

const isProd = import.meta.env.PROD;

/** Base URL for the CRM backend API. */
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

async function authHeaders(extra?: HeadersInit): Promise<Headers> {
  const headers = new Headers(extra);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (entraConfigured() && typeof window !== "undefined") {
    const token = await getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
      return headers;
    }
    const { getMsal } = await import("@/lib/sso");
    const pca = await getMsal();
    if (pca && pca.getAllAccounts().length > 0) return headers;
  }
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
  /** The server's `X-Request-Id`: the line to search its logs for. */
  readonly requestId: string | null;

  constructor(
    method: string,
    path: string,
    status: number,
    detail: string,
    requestId?: string | null,
  ) {
    super(`${method} ${path} failed: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.path = path;
    this.requestId = requestId ?? null;
  }
}

/** True only for a real 404 from the API — never for a network or 5xx failure. */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** True only for a real 403 from the API — the caller is signed in, but the route is gated. */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

/** True only for a real 401 from the API — the token was missing or the account is refused. */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** Permission id from `forbidden:perm-…`, or null when the 403 did not name one. */
export function forbiddenPermission(error: unknown): string | null {
  if (!isForbidden(error)) return null;
  const detail = (error as ApiError).detail;
  if (!detail.startsWith("forbidden:")) return null;
  const perm = detail.slice("forbidden:".length).trim();
  return perm || null;
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

export type TransportSchema<T> = { parse: (value: unknown) => T };

export type ApiInit<T> = {
  signal?: AbortSignal;
  headers?: Record<string, string>;
  schema?: TransportSchema<T>;
};

/** Thin typed GET helper for the live API. */
export async function apiGet<T>(path: string, init?: ApiInit<T>): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: await authHeaders(),
    credentials: "include",
    signal: requestSignal(init?.signal),
  });
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    throw new ApiError(
      "GET",
      path,
      res.status,
      await errorDetail(res),
      res.headers.get("X-Request-Id"),
    );
  }
  const text = await res.text();
  if (!text) return undefined as T;
  const payload: unknown = JSON.parse(text);
  return init?.schema ? init.schema.parse(payload) : parseWire<T>("GET", path, payload);
}

async function apiSend<T>(
  method: "POST" | "PATCH" | "DELETE" | "PUT",
  path: string,
  body?: unknown,
  init?: ApiInit<T>,
): Promise<T> {
  const headers = await authHeaders(
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
    throw new ApiError(
      method,
      path,
      res.status,
      await errorDetail(res),
      res.headers.get("X-Request-Id"),
    );
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  const payload: unknown = JSON.parse(text);
  return init?.schema ? init.schema.parse(payload) : parseWire<T>(method, path, payload);
}

export function apiPost<T>(path: string, body: unknown, init?: ApiInit<T>): Promise<T> {
  return apiSend<T>("POST", path, body, init);
}

export function apiPatch<T>(path: string, body: unknown, init?: ApiInit<T>): Promise<T> {
  return apiSend<T>("PATCH", path, body, init);
}

export function apiPut<T>(path: string, body: unknown, init?: ApiInit<T>): Promise<T> {
  return apiSend<T>("PUT", path, body, init);
}

export function apiDelete<T = void>(path: string, init?: ApiInit<T>): Promise<T> {
  return apiSend<T>("DELETE", path, undefined, init);
}

/** GET that returns a binary Blob (skill zip, reports). */
export async function apiGetBlob(path: string): Promise<{ blob: Blob; headers: Headers }> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: await authHeaders({
      Accept: "application/zip, application/octet-stream, text/csv, application/json",
    }),
    credentials: "include",
    signal: withTimeout(60_000),
  });
  if (!res.ok) {
    throw new ApiError(
      "GET",
      path,
      res.status,
      await errorDetail(res),
      res.headers.get("X-Request-Id"),
    );
  }
  return { blob: await res.blob(), headers: res.headers };
}
export async function apiPostBlob(
  path: string,
  body: unknown,
): Promise<{ blob: Blob; headers: Headers }> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: await authHeaders({
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

/** `api_support._MAX_UPLOAD_BYTES` — the platform cap every route reads unless it narrows it. */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/**
 * Multipart upload helper (no Content-Type — browser sets boundary).
 *
 * The file is checked before it leaves: the server caps by size and reads the
 * extension, and a 25 MB body that is going to be refused anyway is 25 MB the
 * user waits on for nothing. `accept` is the same list the file input carries
 * — an extension (".zip") or a MIME type ("text/plain").
 */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  opts: { maxBytes?: number; accept?: readonly string[] } = {},
): Promise<T> {
  const maxBytes = opts.maxBytes ?? MAX_UPLOAD_BYTES;
  for (const value of form.values()) {
    if (!(value instanceof File)) continue;
    if (value.size > maxBytes) {
      throw new ApiError(
        "POST",
        path,
        413,
        `${value.name} is ${(value.size / 1_048_576).toFixed(1)} MB; the limit is ${(maxBytes / 1_048_576).toFixed(0)} MB`,
      );
    }
    if (opts.accept?.length) {
      const name = value.name.toLowerCase();
      const ok = opts.accept.some((a) =>
        a.startsWith(".") ? name.endsWith(a.toLowerCase()) : value.type === a,
      );
      if (!ok) {
        throw new ApiError(
          "POST",
          path,
          415,
          `${value.name} is not one of ${opts.accept.join(", ")}`,
        );
      }
    }
  }
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: await authHeaders(),
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
    headers: await authHeaders({ Accept: "text/event-stream" }),
    credentials: "include",
    signal: init?.signal,
  });
  if (!res.ok) {
    throw new ApiError(
      "GET",
      path,
      res.status,
      await errorDetail(res),
      res.headers.get("X-Request-Id"),
    );
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
