// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The studio's tabs, rendered against the wire.
//
// Eight panels had no render test (ORG-09 / SKILLS-17). Each one below mounts
// the real panel through the real api/ modules with `fetch` answered from the
// wire samples, and asserts the one thing the panel exists to say — the thing a
// source pin cannot see because the string is in the file whether or not the
// user is shown it. Nothing here names a hook.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentCard } from "@/api/agent-card";
import type { VoiceConfig } from "@/api/types/prompt-studio";
import { DEFAULT_VOICE } from "@/lib/prompt-studio";
import { mountAt } from "@/test/mount";
import { installWireFetch, sample } from "@/test/wire-fetch";

const { SkillsTab } = await import("./panels/SkillsTab");
const { ConnectorsTab } = await import("./panels/ConnectorsTab");
const { EvalsTab } = await import("./panels/EvalsTab");
const { PolicyTab } = await import("./panels/PolicyTab");
const { AgentGraphTab } = await import("./panels/AgentGraphTab");
const { ChangeLogTab } = await import("./ChangeLogTab");
const { PromptEditor } = await import("./PromptEditor");
const { VoicePanel } = await import("./VoicePanel");

const BOT = "kaia-v2-4";
const CARD = sample<{ agentCard: AgentCard }>("GET /agent-studio/cards/{bot_id}").agentCard;

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    "POST /agent-studio/cards/{bot_id}/compile": sample(
      "GET /agent-studio/cards/{bot_id}/effective-contract",
    ),
    "POST /prompt-versions/estimate-tokens": { tokens: 412, promptTokens: 300 },
  });
});

afterEach(() => {
  wire.restore();
});

const at = (element: React.ReactElement) => mountAt(`/agent-studio/${BOT}`, element);

describe("Skills tab", () => {
  it("lists the catalog and offers Attach/Detach only when the card is editable", async () => {
    const onChange = vi.fn();
    at(<SkillsTab botId={BOT} card={CARD} onChange={onChange} />);
    await screen.findByText("broken-ptp-chase");
    expect(screen.getByText("dispute-capture")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /^(Attach|Detach)$/ });
    expect(buttons.length).toBeGreaterThan(0);
    // one click rewrites the card's skills list -- nothing is saved from here
    fireEvent.click(buttons[0]!);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(wire.calls.filter((c) => c.method !== "GET" && !/compile/.test(c.path))).toEqual([]);
  });

  it("is read-only without an onChange", async () => {
    at(<SkillsTab botId={BOT} card={CARD} />);
    await screen.findByText("broken-ptp-chase");
    for (const b of screen.getAllByRole("button", { name: /^(Attach|Detach)$/ })) {
      expect(b).toBeDisabled();
    }
  });
});

describe("Connectors tab", () => {
  it("keeps Unbind reachable for a binding the registry no longer returns", async () => {
    const onChange = vi.fn();
    const card: AgentCard = {
      ...CARD,
      connectors: [{ connector_id: "conn-gone", allow_prefixes: ["ext.gone."] }],
    };
    at(<ConnectorsTab botId={BOT} card={card} onChange={onChange} />);
    await screen.findByText("LMS balance");
    // The approved rows offer Bind; the orphan is named by its id with Unbind.
    expect(screen.getByText("conn-gone")).toBeInTheDocument();
    const unbind = screen.getAllByRole("button", { name: "Unbind" });
    expect(unbind).toHaveLength(1);
    fireEvent.click(unbind[0]!);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ connectors: [] }));
  });
});

describe("Evals tab", () => {
  it("says when a card requires nothing, rather than showing a default it does not have", async () => {
    const card: AgentCard = { ...CARD, eval: undefined };
    at(<EvalsTab botId={BOT} card={card} onChange={vi.fn()} />);
    await screen.findByText("Collections capability");
    expect(screen.getByText(/sets no eval requirements/)).toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
  });

  it("lists the suites and a Run button per suite", async () => {
    at(<EvalsTab botId={BOT} card={CARD} onChange={vi.fn()} promptVersionId="pv-1" />);
    await screen.findByText("Outbound conduct");
    expect(screen.getAllByRole("button", { name: /^Run/ }).length).toBeGreaterThanOrEqual(3);
  });
});

describe("Policy tab", () => {
  it("flags an engine tool the card's locked list dropped, and Restore puts it back", async () => {
    const onChange = vi.fn();
    const card: AgentCard = {
      ...CARD,
      tools: { ...(CARD.tools ?? {}), locked: ["evaluate_authority"] },
    };
    at(<PolicyTab card={card} onChange={onChange} />);
    await screen.findByText("Recommend next offer");
    expect(screen.getByText("not locked on this card")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    const next = onChange.mock.calls[0]![0] as AgentCard;
    expect(next.tools?.locked).toEqual(["evaluate_authority", "recommend_next_offer"]);
    // each engine links to where its mode is set
    expect(screen.getAllByRole("link").length).toBeGreaterThan(0);
  });
});

describe("Agent graph tab", () => {
  it("shows a handoff to a card that is not in the fleet, with Remove", async () => {
    const onChange = vi.fn();
    // the sample card hands off to `supervisor-brief`, which the graph has no node for
    at(<AgentGraphTab botId={BOT} card={CARD} onChange={onChange} />);
    await screen.findByText("not in the fleet");
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" }).at(-1)!);
    const next = onChange.mock.calls[0]![0] as AgentCard;
    expect(next.handoffs?.map((h) => h.to_bot_id)).not.toContain("supervisor-brief");
    expect(next.handoffs?.map((h) => h.to_bot_id)).toContain("insurance-v1");
  });
});

describe("Change log tab", () => {
  it("renders the entries with their chain verdict and says how many are not shown", async () => {
    at(<ChangeLogTab botId={BOT} />);
    await screen.findByText("Change log");
    const log = sample<{ entries: unknown[]; total: number }>("GET /agent-studio/change-log");
    await waitFor(() =>
      expect(
        screen.getByText(new RegExp(`showing ${log.entries.length} of ${log.total}`)),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Load more" })).toBeInTheDocument();
  });
});

describe("Prompt editor", () => {
  it("shows the prompt, and an unknown variable once rather than in two banners", async () => {
    const onChange = vi.fn();
    at(
      <PromptEditor
        value="Hello {customer_first_name}, your {foo} is due."
        onChange={onChange}
        onApplyPreset={vi.fn()}
        lintFindings={[
          { severity: "warn", code: "unknown_variable", message: "unknown variable {foo}" },
        ]}
        botId={BOT}
      />,
    );
    const area = (await screen.findAllByRole("textbox")).find((t) =>
      (t as HTMLTextAreaElement).value.includes("{foo}"),
    );
    expect(area).toBeDefined();
    expect(screen.getAllByText("{foo}")).toHaveLength(1);
    expect(screen.queryByText(/unknown variable \{foo\}/)).not.toBeInTheDocument();
  });
});

describe("Voice panel", () => {
  it("names the bound voice and offers a preview", async () => {
    const value: VoiceConfig = { ...DEFAULT_VOICE };
    at(<VoicePanel value={value} onChange={vi.fn()} cardLocales={["en-IN"]} />);
    await waitFor(() => expect(wire.calls.some((c) => /tts-voices/.test(c.path))).toBe(true));
    expect(
      screen.getAllByText(new RegExp(value.azureVoiceName ?? "Neural")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Preview voice" })).toBeInTheDocument();
  });
});
