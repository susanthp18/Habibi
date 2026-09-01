import { describe, it, expect } from "vitest";
import {
  archiveAvailability,
  changeVerb,
  groupRoster,
  rosterGroupOf,
  sandboxAvailability,
  type ArchivableCard,
  type GroupableCard,
} from "./agent-roster";

const ENTRY = "kaia-v2-4";

function card(over: Partial<ArchivableCard> = {}): ArchivableCard {
  return {
    archivedAt: null,
    isFirstParty: false,
    botId: "clone-abc123",
    entryBotId: ENTRY,
    deploymentStatus: "draft",
    ...over,
  };
}

describe("archiveAvailability", () => {
  it("refuses a first-party card even when it reports published", () => {
    // The regression this branch order exists for: isFirstParty has to come
    // from the server, because a first-party card with a published row reports
    // cardSource "published" and inferring from that enabled a button that
    // then 409'd.
    const a = archiveAvailability(
      card({ isFirstParty: true, botId: "intake-v1", deploymentStatus: "published" }),
    );
    expect(a.allowed).toBe(false);
    expect(a.reason).toBe("First-party cards are re-seeded on API boot");
  });

  it("refuses the card inbound traffic resolves to", () => {
    const a = archiveAvailability(card({ botId: ENTRY, deploymentStatus: "live" }));
    expect(a.allowed).toBe(false);
    expect(a.reason).toBe("This card takes inbound traffic");
  });

  it("allows a live non-entry clone, and says what archiving costs", () => {
    // A live deployment stopped being a blocker on both sides: publish always
    // leaves one active, so refusing on it made the feature unreachable for
    // every card that had ever shipped.
    const a = archiveAvailability(card({ deploymentStatus: "live" }));
    expect(a.allowed).toBe(true);
    expect(a.reason).toBe("Retires the live deployment and takes the card off the roster");
  });

  it("never blocks Restore", () => {
    // Even for a card that would be refused an archive on every other count.
    const a = archiveAvailability(
      card({
        archivedAt: "2026-08-23T08:16:34Z",
        isFirstParty: true,
        botId: ENTRY,
        deploymentStatus: "live",
      }),
    );
    expect(a.allowed).toBe(true);
    expect(a.reason).toBe("Bring this card back onto the roster");
  });

  it("allows an ordinary draft clone with nothing to warn about", () => {
    expect(archiveAvailability(card())).toEqual({ allowed: true });
  });

  it("gives every blocked answer a reason, across the whole branch matrix", () => {
    // The invariant the tooltip fix rests on. A blocked action carrying no
    // reason is exactly the bug that was on screen: a dead button and no way
    // to find out why.
    const statuses = ["live", "published", "draft", "empty"] as const;
    for (const archivedAt of [null, "2026-08-23T08:16:34Z"]) {
      for (const isFirstParty of [false, true]) {
        for (const botId of ["clone-abc123", ENTRY]) {
          for (const deploymentStatus of statuses) {
            const a = archiveAvailability(
              card({ archivedAt, isFirstParty, botId, deploymentStatus }),
            );
            if (!a.allowed) expect(a.reason, JSON.stringify({ isFirstParty, botId })).toBeTruthy();
          }
        }
      }
    }
  });
});

describe("sandboxAvailability", () => {
  it("refuses a card with no version to run", () => {
    const a = sandboxAvailability({ deploymentStatus: "empty" });
    expect(a.allowed).toBe(false);
    expect(a.reason).toBe("No version to run — author and save a draft first");
  });

  it("allows anything that has a version", () => {
    for (const deploymentStatus of ["live", "published", "draft"] as const) {
      expect(sandboxAvailability({ deploymentStatus })).toEqual({ allowed: true });
    }
  });
});

describe("rosterGroupOf", () => {
  it("puts an archived card with the archived ones whatever it used to be", () => {
    expect(rosterGroupOf({ archivedAt: "2026-08-19T04:43:18Z", isFirstParty: true })).toBe(
      "archived",
    );
  });

  it("splits live cards by provenance", () => {
    expect(rosterGroupOf({ archivedAt: null, isFirstParty: true })).toBe("first-party");
    expect(rosterGroupOf({ archivedAt: null, isFirstParty: false })).toBe("clones");
  });
});

describe("groupRoster", () => {
  function row(name: string, over: Partial<GroupableCard> = {}): GroupableCard {
    return { name, botId: name.toLowerCase(), archivedAt: null, isFirstParty: false, ...over };
  }

  it("orders the groups and sorts alphabetically inside each", () => {
    // Input in creation order, first-party interleaved with clones — what the
    // API actually returns.
    const groups = groupRoster([
      row("Webchat"),
      row("Intake", { isFirstParty: true }),
      row("Collections-clone"),
      row("Collections", { isFirstParty: true }),
      row("Probe", { archivedAt: "2026-08-23T08:16:34Z" }),
      row("Audit", { archivedAt: "2026-08-19T04:43:18Z", isFirstParty: true }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["first-party", "clones", "archived"]);
    expect(groups[0].cards.map((c) => c.name)).toEqual(["Collections", "Intake"]);
    expect(groups[1].cards.map((c) => c.name)).toEqual(["Collections-clone", "Webchat"]);
    expect(groups[2].cards.map((c) => c.name)).toEqual(["Audit", "Probe"]);
  });

  it("emits no heading for a group with no cards", () => {
    const groups = groupRoster([row("Intake", { isFirstParty: true })]);
    expect(groups.map((g) => g.key)).toEqual(["first-party"]);
  });

  it("breaks a duplicate-name tie on botId so the order is total", () => {
    const groups = groupRoster([
      row("Collections-clone", { botId: "collections-clone-9ff4b6" }),
      row("Collections-clone", { botId: "collections-clone-1a2b3c" }),
    ]);
    expect(groups[0].cards.map((c) => c.botId)).toEqual([
      "collections-clone-1a2b3c",
      "collections-clone-9ff4b6",
    ]);
  });

  it("returns nothing for an empty roster", () => {
    expect(groupRoster([])).toEqual([]);
  });
});

describe("changeVerb", () => {
  it("maps the four actions the change log writes", () => {
    expect(changeVerb("agent.publish")).toBe("published");
    expect(changeVerb("agent.rollback")).toBe("rolled back");
    expect(changeVerb("agent.archive")).toBe("archived");
    expect(changeVerb("agent.restore")).toBe("restored");
  });

  it("degrades an unknown action into something readable", () => {
    // A build that starts writing a new action must not render "agent.foo_bar".
    expect(changeVerb("agent.foo_bar")).toBe("foo bar");
  });
});
