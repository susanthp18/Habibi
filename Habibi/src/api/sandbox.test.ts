import { describe, expect, it } from "vitest";

import { groundedLabel, groundedSources } from "@/api/sandbox";

// Rehearsal 2026-08-25, card kaia-v2-4: turn 2's footer read
// "3034ms · 1241t · 0 chunks" directly under three "grounded in FAQ" chips. The
// counter read botTurn.chunkIds while the chips read botTurn.chunks, and an
// FAQ-only turn fills only the latter. One list now backs both.
describe("groundedSources", () => {
  const chips = [
    { chunkId: "faq-collections-1", docTitle: "FAQ · collections" },
    { chunkId: "faq-collections-2", docTitle: "FAQ · collections" },
    { chunkId: "faq-collections-3", docTitle: "FAQ · collections" },
  ];

  it("returns the chunks a turn was grounded in", () => {
    expect(groundedSources({ chunks: chips, chunkIds: [] })).toEqual(chips);
  });

  it("counts what it shows when only chunks are populated", () => {
    // The regression: chips 3, counter 0.
    const grounded = groundedSources({ chunks: chips, chunkIds: [] });

    expect(grounded).toHaveLength(chips.length);
  });

  it("falls back to ids when the payload sent ids only", () => {
    expect(groundedSources({ chunkIds: ["kbc-1", "kbc-2"] })).toEqual([
      { chunkId: "kbc-1" },
      { chunkId: "kbc-2" },
    ]);
  });

  it("prefers chunks over ids rather than concatenating them", () => {
    const grounded = groundedSources({
      chunks: [{ chunkId: "kbc-1", docTitle: "Collections Policy" }],
      chunkIds: ["kbc-1"],
    });

    expect(grounded).toEqual([{ chunkId: "kbc-1", docTitle: "Collections Policy" }]);
  });

  it("is empty for an ungrounded turn", () => {
    expect(groundedSources({})).toEqual([]);
    expect(groundedSources({ chunks: [], chunkIds: [] })).toEqual([]);
  });

  it("labels an id-only source by its id, so a chip is never blank", () => {
    const [only] = groundedSources({ chunkIds: ["kbc-7"] });

    expect(groundedLabel(only)).toBe("kbc-7");
  });
});
