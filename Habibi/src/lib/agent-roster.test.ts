import { describe, it, expect } from "vitest";
import {
  archiveAvailability,
  changeVerb,
  groupRoster,
  nextCloneName,
  ROUTING,
  rosterGroupOf,
  sandboxAvailability,
  type ArchivableCard,
  type GroupableCard,
} from "./agent-roster";

function card(over: Partial<ArchivableCard> = {}): ArchivableCard {
  return {
    archivedAt: null,
    isFirstParty: false,
    deploymentStatus: "draft",
    takesInbound: false,
    ...over,
  };
}

describe("archiveAvailability", () => {
  it("refuses a first-party card even when it reports published", () => {
    // The regression this branch order exists for: isFirstParty has to come
    // from the server, because a first-party card with a published row reports
    // cardSource "published" and inferring from that enabled a button that
    // then 409'd.
    const a = archiveAvailability(card({ isFirstParty: true, deploymentStatus: "published" }));
    expect(a.allowed).toBe(false);
    expect(a.reason).toBe("First-party cards are re-seeded on API boot");
  });

  it("refuses whatever the server's entry guard refuses", () => {
    // `takesInbound` is `routing.entry_card_ids` -- the env default or any
    // enabled binding. It used to be rebuilt here from `entryBotId`, which is
    // the voice channel's resolved card: point BOT_ID at a clone while the door
    // routes voice elsewhere and the button enabled, then 409'd.
    const a = archiveAvailability(card({ takesInbound: true, deploymentStatus: "live" }));
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
        takesInbound: true,
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
        for (const takesInbound of [false, true]) {
          for (const deploymentStatus of statuses) {
            const a = archiveAvailability(
              card({ archivedAt, isFirstParty, takesInbound, deploymentStatus }),
            );
            if (!a.allowed)
              expect(a.reason, JSON.stringify({ isFirstParty, takesInbound })).toBeTruthy();
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
    expect(groups[0]?.cards.map((c) => c.name)).toEqual(["Collections", "Intake"]);
    expect(groups[1]?.cards.map((c) => c.name)).toEqual(["Collections-clone", "Webchat"]);
    expect(groups[2]?.cards.map((c) => c.name)).toEqual(["Audit", "Probe"]);
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
    expect(groups[0]?.cards.map((c) => c.botId)).toEqual([
      "collections-clone-1a2b3c",
      "collections-clone-9ff4b6",
    ]);
  });

  it("returns nothing for an empty roster", () => {
    expect(groupRoster([])).toEqual([]);
  });
});

describe("changeVerb", () => {
  it("maps the lifecycle actions the change log writes", () => {
    expect(changeVerb("agent.publish")).toBe("published");
    expect(changeVerb("agent.rollback")).toBe("rolled back");
    expect(changeVerb("agent.archive")).toBe("archived");
    expect(changeVerb("agent.restore")).toBe("restored");
    expect(changeVerb("agent.role_grants")).toBe("updated role grants");
    expect(changeVerb("agent.experiment_rollback")).toBe("rolled back experiment");
    expect(changeVerb("agent.entry_binding")).toBe("changed an entry binding");
  });

  it("degrades an unknown action into something readable", () => {
    // A build that starts writing a new action must not render "agent.foo_bar".
    expect(changeVerb("agent.foo_bar")).toBe("foo bar");
  });
});

describe("ROUTING.handoff.help", () => {
  it("names the cards whose allowlist reaches this one, not the entry card", () => {
    expect(ROUTING.handoff.help({ handoffFrom: ["insurance-v1", "kaia-v2-4"] })).toBe(
      "Reached mid-conversation from the handoff allowlist of insurance-v1, kaia-v2-4.",
    );
  });

  it("names nobody rather than the wrong card when it has no list", () => {
    expect(ROUTING.handoff.help({})).toBe(
      "Reached mid-conversation through another card's handoff allowlist.",
    );
  });
});

describe("nextCloneName", () => {
  it("keeps a name the user typed when the template changes", () => {
    expect(nextCloneName("Collections Tier 2", "Lapse", "Hardship")).toBe("Collections Tier 2");
  });

  it("follows the template while the name is still the form's own", () => {
    expect(nextCloneName("Lapse", "Lapse", "Hardship")).toBe("Hardship");
    expect(nextCloneName("", "Lapse", "Hardship")).toBe("Hardship");
    expect(nextCloneName("  ", undefined, "Hardship")).toBe("Hardship");
  });

  it("leaves the name alone for a template it cannot find", () => {
    expect(nextCloneName("Lapse", "Lapse", undefined)).toBe("Lapse");
  });
});
