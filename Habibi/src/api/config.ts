// -----------------------------------------------------------------------------
// Data-layer configuration — the single switch between mock and live backend.
//
// Phase 1 (now):  USE_MOCK = true  → every fetch* function returns local seed data.
// Phase 2 (later): set VITE_USE_MOCK=false in the frontend .env once the CRM API
//                  is live, and each fetch* function's live branch takes over.
//
// Screens never import seed files directly anymore — they call the hooks in
// src/api/*.ts. That means going live is a per-feature one-line change here,
// not an edit to every screen.
// -----------------------------------------------------------------------------

export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? "true") !== "false";

/** Base URL for the CRM backend API (used once USE_MOCK is false). */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
  try {
    const payload = JSON.parse(raw) as { detail?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail != null) return JSON.stringify(payload.detail);
    return raw;
  } catch {
    return raw;
  }
}

/** Thin typed GET helper for the live API (Phase 2). */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

async function apiSend<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error(await errorDetail(res));
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiSend<T>("POST", path, body);
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiSend<T>("PATCH", path, body);
}

export function apiDelete<T = void>(path: string): Promise<T> {
  return apiSend<T>("DELETE", path);
}

/** POST that returns a binary Blob (e.g. TTS audio/mpeg). */
export async function apiPostBlob(
  path: string,
  body: unknown,
): Promise<{ blob: Blob; headers: Headers }> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "audio/mpeg, application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await errorDetail(res));
  }
  return { blob: await res.blob(), headers: res.headers };
}

/** Multipart upload helper (no Content-Type — browser sets boundary). */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json" },
    body: form,
  });
  if (!res.ok) {
    throw new Error(await errorDetail(res));
  }
  return (await res.json()) as T;
}
