// @vitest-environment jsdom
import "@/test/jsdom";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { useOpenRecord } from "./use-open-record";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);

const firstPage = [{ id: "A" }, { id: "B" }];

function open(id: string | null, fetchOne: (id: string) => Promise<{ id: string }[]>) {
  const setOpenId = vi.fn();
  const hook = renderHook(
    () =>
      useOpenRecord({ queryKey: "t", label: "thing", id, list: firstPage, fetchOne, setOpenId }),
    { wrapper },
  );
  return { ...hook, setOpenId };
}

describe("useOpenRecord", () => {
  it("opens a listed record without a read", () => {
    const fetchOne = vi.fn();
    expect(open("B", fetchOne).result.current).toEqual({ id: "B" });
    expect(fetchOne).not.toHaveBeenCalled();
  });

  it("reads a record that is not on the loaded page by its id", async () => {
    const fetchOne = vi.fn().mockResolvedValue([{ id: "Z" }]);
    const { result } = open("Z", fetchOne);
    await waitFor(() => expect(result.current).toEqual({ id: "Z" }));
    expect(fetchOne).toHaveBeenCalledWith("Z");
  });

  it("closes when the read finds nothing or fails", async () => {
    const missing = open("Z", vi.fn().mockResolvedValue([]));
    await waitFor(() => expect(missing.setOpenId).toHaveBeenCalledWith(null));
    const failed = open("Z", vi.fn().mockRejectedValue(new Error("boom")));
    await waitFor(() => expect(failed.setOpenId).toHaveBeenCalledWith(null));
  });
});
