// @vitest-environment jsdom
// The card campaign flow this file used to pin (a `botId` on campaign create)
// was removed with the Outbound control panel (66a146f6). What the module
// does now is place one operator call through the dial owner -- with a key,
// so a retried click is one attempt, never a second dial.
import "@/test/jsdom";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn().mockResolvedValue({ placed: true }));
vi.mock("./config", async (orig) => ({
  ...(await orig<typeof import("./config")>()),
  apiPost: post,
}));

const { usePlaceCall } = await import("./outbound");

describe("placing an operator call", () => {
  it("goes through the dial owner with the click's idempotency key", async () => {
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => usePlaceCall(), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        customerId: "C-1",
        accountId: "ACC-1",
        phone: "+910000000000",
        idempotencyKey: "click-1",
      }),
    );
    expect(post).toHaveBeenCalledWith(
      "/twilio/voice/outbound",
      { customerId: "C-1", accountId: "ACC-1", to: "+910000000000", objective: "manual_outbound" },
      expect.objectContaining({ headers: { "Idempotency-Key": "click-1" } }),
    );
  });
});
