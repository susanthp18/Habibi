// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { clearWrapDrafts, wrapDraft } from "./wrap-draft";

describe("wrap-up drafts", () => {
  it("are each operator's own, and all go at sign-out", () => {
    const asha = { id: "asha", tenantId: "t-1" };
    const ravi = { id: "ravi", tenantId: "t-1" };
    wrapDraft.write(asha, "HO-1", "asha's note");
    wrapDraft.write(ravi, "HO-1", "ravi's note");
    sessionStorage.setItem("theme-pick", "kept");
    expect(wrapDraft.read(ravi, "HO-1")).toBe("ravi's note");
    expect(wrapDraft.read({ id: "asha", tenantId: "t-2" }, "HO-1")).toBe("");
    clearWrapDrafts();
    expect(wrapDraft.read(asha, "HO-1")).toBe("");
    expect(wrapDraft.read(ravi, "HO-1")).toBe("");
    expect(sessionStorage.getItem("theme-pick")).toBe("kept");
  });
});
