import type { LozengeTone } from "@/components/ui/lozenge";

/**
 * Every verb `agent_core/change_log.py` can write, and how each renders.
 *
 * One table for the chip, the past-tense sentence and the empty-state prose.
 * There were two maps -- one here, one in the fleet index -- and the fleet's
 * had the verbs the tab's lacked, so `agent.role_grants` rendered as a raw
 * wire string on the one screen an auditor reads. The backend test
 * `test_the_screen_knows_every_verb_the_log_can_write` pins this list to the
 * Python constants; a new `record_*` fails there until a row is added here.
 */
export const CHANGE_LOG_ACTIONS = {
  "agent.publish": { label: "Published", verb: "published", tone: "success" },
  "agent.rollback": { label: "Rolled back", verb: "rolled back", tone: "warning" },
  "agent.archive": { label: "Archived", verb: "archived", tone: "neutral" },
  "agent.restore": { label: "Restored", verb: "restored", tone: "information" },
  "agent.role_grants": { label: "Role grants", verb: "updated role grants", tone: "information" },
  "agent.experiment_rollback": {
    label: "Experiment rolled back",
    verb: "rolled back experiment",
    tone: "warning",
  },
  "agent.entry_binding": {
    label: "Entry binding",
    verb: "changed an entry binding",
    tone: "information",
  },
} as const satisfies Record<string, { label: string; verb: string; tone: LozengeTone }>;

export type ChangeLogAction = keyof typeof CHANGE_LOG_ACTIONS;

export function actionLabel(action: string): string {
  return (CHANGE_LOG_ACTIONS as Record<string, { label: string }>)[action]?.label ?? action;
}

export function actionTone(action: string): LozengeTone {
  return (CHANGE_LOG_ACTIONS as Record<string, { tone: LozengeTone }>)[action]?.tone ?? "neutral";
}

/** Past tense, because the log records what happened rather than what to do. */
export function changeVerb(action: string): string {
  return (
    (CHANGE_LOG_ACTIONS as Record<string, { verb: string }>)[action]?.verb ??
    action.replace(/^agent\./, "").replace(/_/g, " ")
  );
}

/** "published, rolled back, archived, …" -- the prose lists what the map knows. */
export function actionVerbList(): string {
  return Object.values(CHANGE_LOG_ACTIONS)
    .map((a) => a.verb)
    .join(", ");
}

/**
 * Postgres's `str(datetime)` uses a space where ISO wants a `T`. The server
 * now sends ISO, but rows read before that fix still carry the space, and
 * `new Date("2026-09-01 10:00:00+00:00")` is Invalid Date in Safari.
 */
export function parseLogTimestamp(at: string | null | undefined): Date | null {
  if (!at) return null;
  const ms = Date.parse(at.replace(" ", "T"));
  return Number.isNaN(ms) ? null : new Date(ms);
}
