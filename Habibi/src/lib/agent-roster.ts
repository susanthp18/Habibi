/**
 * Roster logic for the Agent Studio fleet index, kept apart from the route so
 * it can be tested. `vitest` runs `environment: "node"` with no jsdom, so a
 * function reachable by a test is a function with no React in it.
 *
 * `import type` only: nothing here pulls `@/api/agent-studio` in at runtime.
 */
import type { AgentCardSummary } from "@/api/agent-studio";
import type { LozengeTone } from "@/components/ui/lozenge";

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
  "archivedAt" | "isFirstParty" | "deploymentStatus" | "takesInbound"
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
 * - Inbound traffic is refused because it would resolve to a retired card.
 *   `takesInbound` is the server's own guard (`routing.entry_card_ids`), sent
 *   rather than rebuilt here. Rebuilding it from `entryBotId` was wrong: that
 *   is `resolve_entry("voice")`, not the env default the server refuses, so
 *   with the door routing voice elsewhere the button enabled and then 409'd.
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
  if (card.takesInbound) {
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

/**
 * Routing, not deployment. Every published card used to read "live · 100%",
 * which described its deployment row and said nothing about whether traffic
 * can reach it.
 *
 * The first fix over-corrected: it walked the graph from BOT_ID alone, so
 * Intake — a live front door at 100% traffic that routes *to* Collections —
 * read "unreachable" beside two empty scaffolds that genuinely are. A card
 * holding its own active deployment is addressable by bot_id, so it gets
 * `direct` and `unreachable` goes back to meaning dead config.
 */
export const ROUTING: Record<
  AgentCardSummary["reachability"],
  {
    label: string;
    tone: LozengeTone;
    help: (card: Partial<Pick<AgentCardSummary, "handoffFrom">>) => string;
  }
> = {
  entry: {
    label: "takes inbound",
    tone: "success",
    help: () => "Inbound traffic resolves to this card.",
  },
  handoff: {
    label: "via handoff",
    tone: "information",
    // The cards whose allowlist names this one, from the server's walk. It
    // used to name the entry card for every handoff, which was wrong whenever
    // the edge started anywhere else -- Supervisor "from intake-v1", when only
    // Collections and Insurance list it. A caller without the list (the graph
    // tab's nodes) gets the claim without a name rather than a wrong one.
    help: ({ handoffFrom }) =>
      handoffFrom?.length
        ? `Reached mid-conversation from the handoff allowlist of ${handoffFrom.join(", ")}.`
        : "Reached mid-conversation through another card's handoff allowlist.",
  },
  direct: {
    label: "direct only",
    tone: "information",
    help: () =>
      "Addressed directly by bot id — it has its own live deployment — but no reachable card hands off to it.",
  },
  unreachable: {
    label: "unreachable",
    tone: "warning",
    help: () =>
      "Nothing routes here — no deployment of its own, and not on any reachable card's allowlist.",
  },
  archived: {
    label: "archived",
    tone: "neutral",
    help: () => "Retired. Kept for audit; takes no traffic.",
  },
};

/**
 * The Name field when the template changes. A name the user typed survives;
 * one the form filled in (empty, or still the previous template's label)
 * follows the new template. Picking a template used to overwrite whatever was
 * typed.
 */
export function nextCloneName(
  current: string,
  previousTemplateLabel: string | undefined,
  nextTemplateLabel: string | undefined,
): string {
  if (nextTemplateLabel === undefined) return current;
  const untouched = current.trim() === "" || current === previousTemplateLabel;
  return untouched ? nextTemplateLabel : current;
}

export { changeVerb } from "@/lib/change-log-actions";
