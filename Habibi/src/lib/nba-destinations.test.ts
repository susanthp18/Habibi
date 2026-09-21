import { describe, expect, it } from "vitest";

import type { NbaItem } from "@/api/types/customer-insights";
import { nbaDestination, nbaPrimaryLabel } from "./nba-destinations";

function item(action: NbaItem["action"], extra: Partial<NbaItem> = {}): NbaItem {
  return {
    id: "n1",
    rank: 1,
    title: action,
    reason: "because",
    action,
    priority: "medium",
    ...extra,
  };
}

describe("nbaDestination", () => {
  it("does not map schedule onto callbacks", () => {
    expect(nbaDestination(item("schedule"), "c-1")).toEqual({ kind: "emi", customerId: "c-1" });
    expect(nbaDestination(item("callback"), "c-1")).toEqual({
      kind: "callbacks",
      customerId: "c-1",
    });
  });

  it("hides wait and sends advisory to the cases tab", () => {
    expect(nbaDestination(item("wait"), "c-1")).toEqual({ kind: "none" });
    expect(nbaPrimaryLabel(item("wait"))).toBeNull();
    expect(nbaDestination(item("call", { advisory: true }), "c-1")).toEqual({
      kind: "view_decision",
      tab: "cases",
      customerId: "c-1",
    });
    expect(nbaPrimaryLabel(item("call", { advisory: true }))).toBe("View decision");
  });

  it("lands plan, message, mandate, field and legal on their screens", () => {
    expect(nbaDestination(item("plan"), "c-1")).toEqual({ kind: "plan", customerId: "c-1" });
    expect(nbaDestination(item("message"), "c-1")).toEqual({
      kind: "inbox_or_sheet",
      customerId: "c-1",
    });
    expect(nbaDestination(item("mandate"), "c-1")).toEqual({
      kind: "ops",
      tab: "mandates",
      customerId: "c-1",
    });
    expect(nbaDestination(item("field"), "c-1")).toEqual({
      kind: "ops",
      tab: "field",
      customerId: "c-1",
    });
    expect(nbaDestination(item("legal"), "c-1")).toEqual({
      kind: "ops",
      tab: "legal",
      customerId: "c-1",
    });
    expect(nbaDestination(item("call"), "c-1")).toEqual({ kind: "place_call", customerId: "c-1" });
  });
});
