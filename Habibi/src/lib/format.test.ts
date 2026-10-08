// -----------------------------------------------------------------------------
// The compact-money ladder, asserted against the SAME table as
// backend/tests/test_money_formatting.py::COMPACT_CASES.
//
// Two implementations of one ladder is a standing invitation to drift, and this
// pair has drifted before: the backend printed one suffix style where this side
// printed another, and floored every sub-unit amount to zero — the exact thing
// main.py says a metering figure must never be shown as. Keeping the two tables
// byte-identical is what stops that happening again quietly.
//
// `_` in a table stands for the no-break space Intl prints before the symbol
// and the compact suffix.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import { fmtMoney, inrCompact } from "./format";

const v = (text: string) => text.replace(/_/g, " ");

const LADDER: Array<[number, string]> = [
  [0, v("0_₫")],
  [0.00004, v("<0,0001_₫")],
  [0.0001, v("0,0001_₫")],
  [0.004, v("0,0040_₫")],
  [0.9999, v("0,9999_₫")],
  [1, v("1,00_₫")],
  [12.5, v("12,50_₫")],
  [999.99, v("999,99_₫")],
  [1_000, v("1_N_₫")],
  [1_500, v("1,5_N_₫")],
  [99_999, v("100_N_₫")],
  [100_000, v("100_N_₫")],
  [1_234_567, v("1,2_Tr_₫")],
  [9_999_999, v("10_Tr_₫")],
  [10_000_000, v("10_Tr_₫")],
  [45_000_000, v("45_Tr_₫")],
  [4_500_000_000, v("4,5_T_₫")],
];

describe("inrCompact", () => {
  it.each(LADDER)("formats %d as %s", (value, expected) => {
    expect(inrCompact(value)).toBe(expected);
  });

  it("mirrors the ladder for negatives, sign before the number", () => {
    for (const [value, expected] of LADDER) {
      if (value === 0) continue;
      expect(inrCompact(-value)).toBe(`-${expected}`);
    }
  });

  it("never renders a nonzero amount as a plain zero", () => {
    // A call metered at a fraction of a đồng is not a free call. This is the
    // distinction main.py:1038 asks for in as many words.
    for (const tiny of [0.00009, 0.000001, Number.MIN_VALUE]) {
      expect(inrCompact(tiny)).not.toBe(v("0_₫"));
      expect(inrCompact(tiny)).toBe(v("<0,0001_₫"));
    }
  });

  it("promotes a suffix that rounds up to a thousand, as the backend does", () => {
    expect(inrCompact(999_940)).toBe(v("999,9_N_₫"));
    expect(inrCompact(999_960)).toBe(v("1_Tr_₫"));
  });

  it("gives an unusable number the zero reading rather than NaN", () => {
    expect(inrCompact(Number.NaN)).toBe(v("0_₫"));
  });
});

describe("fmtMoney", () => {
  it("writes whole đồng the vi-VN way, as backend money_inr.inr does", () => {
    expect(fmtMoney(1_234_567)).toBe(v("1.234.567_₫"));
    expect(fmtMoney(-500)).toBe(v("-500_₫"));
    expect(fmtMoney(null)).toBe(v("0_₫"));
  });
});

// -----------------------------------------------------------------------------
// Unit *rates* go through the same ladder. The billing table derives Usage from
// the rate it prints, so a rate rounded to whole units makes the row state two
// contradictory things: "715.5k tokens" at "0 ₫" that somehow cost 47,72 ₫.
// -----------------------------------------------------------------------------

describe("inrCompact as the unit-rate format", () => {
  it("keeps a sub-unit rate legible instead of rounding it to zero", () => {
    // The live llm_chat / llm_embed rates the Usage column divides by.
    expect(inrCompact(0.0667)).toBe(v("0,0667_₫"));
    expect(inrCompact(0.0017)).toBe(v("0,0017_₫"));
  });

  it("keeps the decimals on a just-over-one rate rather than flattening to 1", () => {
    // Azure Speech STT (per minute) and TTS (per 1K chars).
    expect(inrCompact(1.4333)).toBe(v("1,43_₫"));
    expect(inrCompact(1.29)).toBe(v("1,29_₫"));
  });
});
