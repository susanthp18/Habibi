/**
 * The compiler's four-word verdict vocabulary, in one place.
 *
 * `GateStatus` is `pass | fail | warn | skipped` and every surface that renders
 * it had re-derived the mapping locally, by writing down the cases it happened
 * to remember. The two that get forgotten are the two that are not `pass` and
 * not `fail`:
 *
 * - The change log filtered `v !== "pass" && v !== "skipped"` and printed the
 *   remainder in red as "gates failed: …". G10 legitimately emits `warn`, so a
 *   publish that the compiler *allowed* was displayed as FAILED — on the screen
 *   whose entire purpose is to be the record an auditor reads.
 * - The Evals tab treated any non-"pass" report as danger, so a `skipped` suite
 *   rendered red directly beneath the tab's own copy saying "Skipped is honest".
 *
 * Both are the same mistake, and it is not one that gets fixed by fixing two
 * call sites — it gets fixed by there being one mapping to import. Anything
 * outside the vocabulary falls through to neutral and is shown verbatim rather
 * than being bucketed into a verdict nobody computed.
 */
import type { LozengeTone } from "@/components/ui/lozenge";

export type GateStatus = "pass" | "fail" | "warn" | "skipped";

export const GATE_TONE: Record<GateStatus, LozengeTone> = {
  pass: "success",
  fail: "danger",
  warn: "warning",
  skipped: "neutral",
};

export const GATE_LABEL: Record<GateStatus, string> = {
  pass: "passed",
  fail: "failed",
  warn: "warned",
  skipped: "skipped",
};

export function gateTone(status: string): LozengeTone {
  return GATE_TONE[status as GateStatus] ?? "neutral";
}

/** Blocks a publish. `warn` does not, which is the whole point of it existing. */
export function isGateFailure(status: string): boolean {
  return status === "fail";
}

/** Ran and had something to say, short of failing. */
export function isGateWarning(status: string): boolean {
  return status === "warn";
}

/**
 * Split a recorded gate map into the two groups a reader cares about.
 *
 * Returns gate NAMES, not entries, because every caller only ever printed the
 * names.
 */
export function partitionGates(gates: Record<string, string>): {
  failed: string[];
  warned: string[];
  total: number;
} {
  const entries = Object.entries(gates);
  return {
    failed: entries.filter(([, v]) => isGateFailure(v)).map(([k]) => k),
    warned: entries.filter(([, v]) => isGateWarning(v)).map(([k]) => k),
    total: entries.length,
  };
}
