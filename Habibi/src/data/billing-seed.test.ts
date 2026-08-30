// -----------------------------------------------------------------------------
// The compact-money ladder, asserted against the SAME table as
// backend/tests/test_money_formatting.py::COMPACT_CASES.
//
// Two implementations of one ladder is a standing invitation to drift, and this
// pair has drifted before: the backend printed "₹1.5 K" where this side printed
// "₹1.5k", and the backend floored every sub-rupee amount to "₹0" — the exact
// thing main.py says a metering figure must never be shown as. Keeping the two
// tables byte-identical is what stops that happening again quietly.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import { inrCompact } from "./billing-seed";

const LADDER: Array<[number, string]> = [
  [0, "₹0"],
  [0.00004, "<₹0.0001"],
  [0.0001, "₹0.0001"],
  [0.004, "₹0.0040"],
  [0.9999, "₹0.9999"],
  [1, "₹1.00"],
  [12.5, "₹12.50"],
  [999.99, "₹999.99"],
  [1_000, "₹1.0k"],
  [1_500, "₹1.5k"],
  [99_999, "₹100.0k"],
  [1_00_000, "₹1.0L"],
  [12_34_567, "₹12.3L"],
  [99_99_999, "₹100.0L"],
  [1_00_00_000, "₹1.0Cr"],
  [4_50_00_000, "₹4.5Cr"],
];

describe("inrCompact", () => {
  it.each(LADDER)("formats %d as %s", (value, expected) => {
    expect(inrCompact(value)).toBe(expected);
  });

  it("mirrors the ladder for negatives, sign outside the symbol", () => {
    for (const [value, expected] of LADDER) {
      if (value === 0) continue;
      expect(inrCompact(-value)).toBe(`-${expected}`);
    }
  });

  it("never renders a nonzero amount as a plain zero", () => {
    // A call metered at a fraction of a paisa is not a free call. This is the
    // distinction main.py:1038 asks for in as many words.
    for (const tiny of [0.00009, 0.000001, Number.MIN_VALUE]) {
      expect(inrCompact(tiny)).not.toBe("₹0");
      expect(inrCompact(tiny)).toBe("<₹0.0001");
    }
  });

  it("uses lowercase k and no space before any suffix", () => {
    expect(inrCompact(1_500)).not.toContain(" ");
    expect(inrCompact(12_34_567)).not.toContain(" ");
    expect(inrCompact(4_50_00_000)).not.toContain(" ");
    expect(inrCompact(1_500)).toContain("k");
    expect(inrCompact(1_500)).not.toContain("K");
  });

  it("gives an unusable number the zero reading rather than NaN", () => {
    expect(inrCompact(Number.NaN)).toBe("₹0");
  });
});

// -----------------------------------------------------------------------------
// Unit *rates* go through the same ladder. The billing table derives Usage from
// the rate it prints, so a rate rounded to whole rupees makes the row state two
// contradictory things: "715.5k tokens" at "₹0" that somehow cost ₹47.72.
// -----------------------------------------------------------------------------

describe("inrCompact as the unit-rate format", () => {
  it("keeps a sub-rupee rate legible instead of rounding it to ₹0", () => {
    // The live llm_chat / llm_embed rates the Usage column divides by.
    expect(inrCompact(0.0667)).toBe("₹0.0667");
    expect(inrCompact(0.0017)).toBe("₹0.0017");
  });

  it("keeps the paise on a just-over-a-rupee rate rather than flattening to ₹1", () => {
    // Azure Speech STT (per minute) and TTS (per 1K chars). Both round to "₹1".
    expect(inrCompact(1.4333)).toBe("₹1.43");
    expect(inrCompact(1.29)).toBe("₹1.29");
  });
});
