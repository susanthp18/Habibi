import type { CheckRun } from "@/api/voice-studio";

const TREND_RUNS = 12;

/** Pass rate of the last finished runs, oldest to newest: is the agent getting better or worse? */
export function passRates(runs: CheckRun[]): { id: string; pct: number; label: string }[] {
  return runs
    .filter((r) => r.status === "done" && r.passed + r.failed > 0)
    .slice(0, TREND_RUNS)
    .reverse()
    .map((r) => ({
      id: r.id,
      pct: Math.round((100 * r.passed) / (r.passed + r.failed)),
      label: `${new Date(r.createdAt).toLocaleString()}: ${r.passed} of ${r.passed + r.failed} passed`,
    }));
}
