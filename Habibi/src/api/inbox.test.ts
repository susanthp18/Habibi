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
import type { ThreadSummary } from "@/api/types/inbox";

type Thread = ThreadSummary;

function thread(id: string, lastAt: string, lastTime: string): Thread {
  return { id, lastAt, updatedAt: lastAt, lastTime, customer: id } as unknown as Thread;
}

describe("compareThreads", () => {
  it("orders by the last message, newest first", () => {
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
    // Server: ORDER BY COALESCE(last message, created_at) DESC, cv.id
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

  it("does not move a thread for a change nobody said anything in", () => {
    // `updatedAt` is the delta watermark: a takeover or a receipt moves it.
    const talked = thread("CV-1", "2026-08-23T06:00:00.000000+00:00", "11:30 AM");
    const touched = {
      ...thread("CV-2", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"),
      updatedAt: "2026-08-23T07:00:00.000000+00:00",
    } as Thread;
    expect([touched, talked].sort(compareThreads).map((t) => t.id)).toEqual(["CV-1", "CV-2"]);
  });

  it("treats a missing lastAt as oldest rather than throwing", () => {
    const dated = thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM");
    const undated = {
      ...thread("CV-2", "", "11:30 AM"),
      lastAt: undefined,
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

  it("replaces a row with its delta", () => {
    const prev = [
      { ...thread("CV-1", "2026-08-23T05:00:00.000000+00:00", "10:30 AM"), awaitingReply: 2 },
    ];
    const delta = {
      ...thread("CV-1", "2026-08-23T06:00:00.000000+00:00", "11:30 AM"),
      awaitingReply: 0,
    };
    expect(mergeThreads(prev as Thread[], [delta as Thread])[0]?.awaitingReply).toBe(0);
  });
});
