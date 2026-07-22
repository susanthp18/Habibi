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

async function apiSend<T>(method: "POST" | "PATCH", path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${method} ${path} failed: ${res.status} ${res.statusText} ${detail}`);
  }
  return (await res.json()) as T;
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiSend<T>("POST", path, body);
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiSend<T>("PATCH", path, body);
}
