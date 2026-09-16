// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

const sso = vi.hoisted(() => ({
  entraConfigured: vi.fn(() => true),
  getAccessToken: vi.fn(async () => "eyJhbGciOiJSUzI1NiJ9.e30.sig"),
  getMsal: vi.fn(async () => ({ getAllAccounts: () => [{ homeAccountId: "oid" }] })),
}));

vi.mock("@/lib/sso", () => sso);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("operator API auth", () => {
  it("sends the Entra access token and not VITE_API_KEY when a session exists", async () => {
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ id: "r1" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { apiGet } = await import("./config");
    await apiGet("/me", { schema: z.object({ id: z.string() }) });

    expect(fetchMock).toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig");
    expect(headers.get("X-API-Key")).toBeNull();
    expect(headers.get("X-Actor-User-Id")).toBeNull();
  });
});
