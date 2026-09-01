/**
 * Roster logic for the Agent Studio fleet index, kept apart from the route so
 * it can be tested. `vitest` runs `environment: "node"` with no jsdom, so a
 * function reachable by a test is a function with no React in it.
 *
 * `import type` only: nothing here pulls `@/api/agent-studio` in at runtime.
 */
import type { AgentCardSummary } from "@/api/agent-studio";

/**
 * Whether an action can be taken, and one sentence about it either way.
 *
 * The two halves used to be separate — `canArchive` returned a boolean and
 * `archiveReason` returned a string — and they disagreed about what a reason
 * was. Two of that function's four branches explained a *block* ("first-party
 * cards are re-seeded on API boot") and two explained a *consequence* of going
 * ahead ("retires the live deployment"), with nothing in the return type to
 * tell them apart. A button given only the string cannot know whether to show
 * it as a refusal or a warning. Returning both together is what makes that
 * decidable.
 */
export type ActionAvailability = {
  /** False means the click is inert, and `reason` says why. */
  allowed: boolean;
  /**
   * Shown on hover and announced to a screen reader. Present on an allowed
   * action too, where it describes what will happen rather than what stopped.
   */
  reason?: string;
};

/** The fields `archiveAvailability` reads. Narrow on purpose: a test fixture
 *  should not have to invent a whole card to exercise one branch. */
export type ArchivableCard = Pick<
  AgentCardSummary,
  "archivedAt" | "isFirstParty" | "botId" | "entryBotId" | "deploymentStatus"
>;

/**
 * Mirrors `db.archive_agent_studio_card` so the button never offers a 409.
 *
 * Branch order is load-bearing and must stay as written:
 *
 * - `archivedAt` first, because Restore is never blocked.
 * - `isFirstParty` comes from the server. Inferring it from `cardSource` was
 *   wrong — a first-party card with a published row reports "published", so
 *   its button enabled and then failed.
 * - The entry bot is refused because inbound traffic would resolve to a
 *   retired card.
 * - A live deployment is *not* a blocker. It used to be, on both sides, and
 *   that made the button dead for every card that had ever shipped: publish
 *   always leaves an active deployment and rollback only swaps which one is
 *   active. Archiving retires the deployment, which is what taking a card out
 *   of service means, so this branch is a consequence and not a refusal.
 */
export function archiveAvailability(card: ArchivableCard): ActionAvailability {
  if (card.archivedAt) {
    return { allowed: true, reason: "Bring this card back onto the roster" };
  }
  if (card.isFirstParty) {
    return { allowed: false, reason: "First-party cards are re-seeded on API boot" };
  }
  if (card.botId === card.entryBotId) {
    return { allowed: false, reason: "This card takes inbound traffic" };
  }
  if (card.deploymentStatus === "live") {
    return {
      allowed: true,
      reason: "Retires the live deployment and takes the card off the roster",
    };
  }
  return { allowed: true };
}

/**
 * A card with no prompt version has nothing to rehearse: the sandbox would
 * open and fall back to its default bot, which is a different card than the
 * one clicked.
 */
export function sandboxAvailability(
  card: Pick<AgentCardSummary, "deploymentStatus">,
): ActionAvailability {
  if (card.deploymentStatus === "empty") {
    return { allowed: false, reason: "No version to run — author and save a draft first" };
  }
  return { allowed: true };
}

export type RosterGroupKey = "first-party" | "clones" | "archived";

export type RosterGroup<T> = {
  key: RosterGroupKey;
  label: string;
  cards: T[];
};

/** Archived wins over first-party: a retired card belongs with the retired
 *  ones whatever it used to be. */
export function rosterGroupOf(
  card: Pick<AgentCardSummary, "archivedAt" | "isFirstParty">,
): RosterGroupKey {
  if (card.archivedAt) return "archived";
  return card.isFirstParty ? "first-party" : "clones";
}

const GROUP_ORDER: { key: RosterGroupKey; label: string }[] = [
  { key: "first-party", label: "First-party mouths" },
  { key: "clones", label: "Tenant clones" },
  { key: "archived", label: "Archived" },
];

export type GroupableCard = Pick<
  AgentCardSummary,
  "archivedAt" | "isFirstParty" | "name" | "botId"
>;

/**
 * The roster in reading order.
 *
 * The API returns cards in row order, which is creation order, so the four
 * first-party mouths arrive interleaved with whatever clones happened to be
 * made between them — nine cards with no way to see which four are the
 * product. Sorting is alphabetical within a group rather than by reachability
 * or deployment: a roster that reorders itself whenever a deployment changes
 * is harder to navigate than one that always looks the same, and the
 * `unreachable` lozenge already carries that warning on the card.
 *
 * Empty groups return nothing, so a tenant with no clones sees no heading for
 * them.
 */
export function groupRoster<T extends GroupableCard>(cards: readonly T[]): RosterGroup<T>[] {
  const buckets = new Map<RosterGroupKey, T[]>();
  for (const card of cards) {
    const key = rosterGroupOf(card);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(card);
    else buckets.set(key, [card]);
  }
  const groups: RosterGroup<T>[] = [];
  for (const { key, label } of GROUP_ORDER) {
    const bucket = buckets.get(key);
    if (!bucket?.length) continue;
    // botId breaks the tie so the order is total: two clones of one template
    // carry the same display name until someone renames them.
    bucket.sort((a, b) => a.name.localeCompare(b.name) || a.botId.localeCompare(b.botId));
    groups.push({ key, label, cards: bucket });
  }
  return groups;
}

/** Past tense, because the log records what happened rather than what to do. */
const CHANGE_VERBS: Record<string, string> = {
  "agent.publish": "published",
  "agent.rollback": "rolled back",
  "agent.archive": "archived",
  "agent.restore": "restored",
};

export function changeVerb(action: string): string {
  return CHANGE_VERBS[action] ?? action.replace(/^agent\./, "").replace(/_/g, " ");
}
