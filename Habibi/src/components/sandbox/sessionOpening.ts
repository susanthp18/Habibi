/** The two turns a rehearsal opens with before the server has a run: the session note and the scripted greeting. */
import type { Scenario, SandboxTurn } from "@/api/types/sandbox";

export function makeId() {
  return Math.random().toString(36).slice(2, 10);
}

export function openingTurns(s: Scenario): SandboxTurn[] {
  const opening = (s.openingBot || "")
    .replaceAll("{customer_name}", s.persona.name)
    .replaceAll("{agent_name}", "Priya")
    .replaceAll("{bank_name}", "HDFC Bank")
    .replaceAll("{language}", s.persona.language);
  return [
    {
      id: makeId(),
      role: "system",
      text: `New session · ${s.title}`,
      ts: Date.now(),
      systemKind: "info",
    },
    {
      id: makeId(),
      role: "bot",
      text: opening || `Hello, this is Priya from HDFC Bank. Am I speaking with ${s.persona.name}?`,
      ts: Date.now(),
      chunkIds: [],
      latencyMs: 0,
      tokens: 0,
    },
  ];
}

/** Hand the browser a JSON file: the transcript the sandbox holds, named for the run. */
export function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
