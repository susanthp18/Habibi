// -----------------------------------------------------------------------------
// Inbox delta-merge ordering.
//
// The list is polled every 1.5–4s: a full list on the first poll and every
// ~15th, deltas in between. A full poll renders the server's order verbatim; a
// delta poll re-sorts on the client. If those two orders disagree, rows swap
// places on their own once a minute.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import { compareThreads, mergeThreads } from "./inbox";
import type { Thread } from "@/data/inbox-seed";

function thread(id: string, updatedAt: string, lastTime: string): Thread {
  return {
    id,
    updatedAt,
    lastTime,
    customer: id,
    messages: [],
    ragSuggestions: [],
  } as unknown as Thread;
}

describe("compareThreads", () => {
  it("orders by updatedAt, newest first", () => {
    const older = thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM");
    const newer = thread("CV-2", "2026-08-23T06:00:00.000000+00:00", "11:30 AM");
    expect([older, newer].sort(compareThreads).map((t) => t.id)).toEqual(["CV-2", "CV-1"]);
  });

  it("does not compare 12-hour clock strings", () => {
    // "9:40 AM" > "10:29 AM" lexicographically, so the older thread sorted
    // first whenever the hour had one digit fewer. Every seeded thread shares
    // an updatedAt to the microsecond — one bulk transaction — so this
    // tiebreak decided the whole list.
    const nine = thread("CV-B", "2026-08-23T05:04:18.379714+00:00", "9:40 AM");
    const ten = thread("CV-A", "2026-08-23T05:04:18.379714+00:00", "10:29 AM");
    const byClock = [ten, nine].sort((a, b) => (b.lastTime || "").localeCompare(a.lastTime || ""));
    expect(byClock.map((t) => t.id)).toEqual(["CV-B", "CV-A"]); // the old bug

    expect([ten, nine].sort(compareThreads).map((t) => t.id)).toEqual(["CV-A", "CV-B"]);
  });

  it("breaks ties by id, ascending — the server's own tiebreak", () => {
    // Server: ORDER BY COALESCE(updated_at, created_at) DESC, cv.id
    const at = "2026-08-23T05:04:18.379714+00:00";
    const rows = [
      thread("CV-C", at, "1:00 PM"),
      thread("CV-A", at, "2:00 PM"),
      thread("CV-B", at, "3:00 PM"),
    ];
    expect(rows.sort(compareThreads).map((t) => t.id)).toEqual(["CV-A", "CV-B", "CV-C"]);
  });

  it("is a total order — sorting twice does not reshuffle", () => {
    const at = "2026-08-23T05:04:18.379714+00:00";
    const rows = [
      thread("CV-C", at, "9:40 AM"),
      thread("CV-A", at, "10:29 AM"),
      thread("CV-B", at, "8:00 AM"),
    ];
    const once = [...rows].sort(compareThreads).map((t) => t.id);
    const twice = [...rows]
      .sort(compareThreads)
      .sort(compareThreads)
      .map((t) => t.id);
    expect(twice).toEqual(once);
  });

  it("treats a missing updatedAt as oldest rather than throwing", () => {
    const dated = thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM");
    const undated = {
      ...thread("CV-2", "", "11:30 AM"),
      updatedAt: undefined,
    } as unknown as Thread;
    expect([undated, dated].sort(compareThreads).map((t) => t.id)).toEqual(["CV-1", "CV-2"]);
  });
});

describe("mergeThreads", () => {
  it("keeps the previous list when a delta poll returns nothing", () => {
    const prev = [thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM")];
    expect(mergeThreads(prev, [])).toBe(prev);
  });

  it("upserts a delta and re-sorts into server order", () => {
    const prev = [
      thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"),
      thread("CV-2", "2026-08-23T04:00:00.000000+00:00", "9:30 AM"),
    ];
    const merged = mergeThreads(prev, [
      thread("CV-2", "2026-08-23T07:00:00.000000+00:00", "12:30 PM"),
    ]);
    expect(merged.map((t) => t.id)).toEqual(["CV-2", "CV-1"]);
  });

  it("never wipes a cached transcript with a delta that omits it", () => {
    const prev = [
      {
        ...thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"),
        messages: [{ id: "MSG-1", sender: "customer", text: "hi", time: "10:30 AM" }],
      } as unknown as Thread,
    ];
    const delta = {
      id: "CV-1",
      updatedAt: "2026-08-23T06:00:00.000000+00:00",
    } as unknown as Thread;
    expect(mergeThreads(prev, [delta])[0].messages).toHaveLength(1);
  });
});
