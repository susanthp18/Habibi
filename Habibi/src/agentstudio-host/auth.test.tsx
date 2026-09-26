// @vitest-environment jsdom
import "@/test/jsdom";

import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/me", () => ({
  useMe: () => ({ data: { id: "operator-1", name: "Operator" }, isLoading: false }),
}));
vi.mock("@/api/studio-engine", () => ({ studioAuthHeaders: vi.fn() }));
vi.mock("@/lib/sso", () => ({ signOut: vi.fn() }));

const { useAuth } = await import("./auth");

describe("Studio auth adapter", () => {
  it("keeps the user, callbacks, and adapter identity stable across renders", () => {
    const hook = renderHook(() => useAuth());
    const first = hook.result.current;
    hook.rerender();
    expect(hook.result.current).toBe(first);
    expect(hook.result.current.user).toBe(first.user);
    expect(hook.result.current.redirectToLogin).toBe(first.redirectToLogin);
  });
});
