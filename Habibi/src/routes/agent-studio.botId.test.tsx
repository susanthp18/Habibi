// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The card editor, rendered against the wire.
//
// This is the pin under which the route's state moves into a reducer: it
// renders the real page through the real api/ modules with `fetch` answered
// from the wire samples, edits the prompt, and asserts what the autosave sent.
// Nothing here names a hook, a setter or a piece of state -- so the page can be
// rewired underneath it and the assertion stays the same.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { PromptVersion } from "@/api/types/prompt-studio";
import { mountAt } from "@/test/mount";
import { installWireFetch, sample, type WireCall } from "@/test/wire-fetch";

const { PromptStudioPage } = await import("./_app.agent-studio.$botId.lazy");

const BOT = "kaia-v2-4";
const versions = sample<PromptVersion[]>("GET /prompt-versions");
const live = versions.find((v) => v.botId === BOT && v.status === "published")!;

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    // the sample list spans every bot; the real route filters by botId
    "GET /prompt-versions": (call: WireCall) => {
      const bot = new URLSearchParams(call.search).get("botId");
      return bot ? versions.filter((v) => v.botId === bot) : versions;
    },
    "POST /prompt-versions/lint": { findings: [] },
    "POST /agent-studio/cards/{bot_id}/compile": sample(
      "GET /agent-studio/cards/{bot_id}/effective-contract",
    ),
    "POST /prompt-versions": (call: WireCall) => ({
      ...live,
      ...(call.body as object),
      id: "pv-draft-test",
      status: "draft",
    }),
  });
});

afterEach(() => {
  wire.restore();
});

const mount = () =>
  mountAt("/agent-studio/$botId", <PromptStudioPage botId={BOT} />, {
    entry: `/agent-studio/${BOT}`,
  });

/** The system prompt textarea, once hydration has put the live prompt in it. */
async function promptEditor(): Promise<HTMLTextAreaElement> {
  return waitFor(
    () => {
      const area = Array.from(document.querySelectorAll("textarea")).find(
        (t) => t.value === live.prompt,
      );
      expect(area).toBeDefined();
      return area!;
    },
    { timeout: 15_000 },
  );
}

describe("/agent-studio/$botId", () => {
  it(
    "hydrates the editor from the published version and names it in the header",
    { timeout: 30_000 },
    async () => {
      mount();
      const editor = await promptEditor();
      expect(editor).toBeInTheDocument();
      expect(screen.getAllByText(new RegExp(live.label!)).length).toBeGreaterThan(0);
      // the reads a hydration costs, and nothing written
      expect(wire.calls.filter((c) => c.method !== "GET")).toEqual(
        wire.calls.filter((c) => c.method !== "GET" && /lint|compile/.test(c.path)),
      );
    },
  );

  it(
    "autosaves an edited prompt as a new draft that carries the whole version",
    { timeout: 30_000 },
    async () => {
      mount();
      const editor = await promptEditor();
      fireEvent.change(editor, { target: { value: `${live.prompt}\nEdited in the pin.` } });
      const save = await waitFor(
        () => {
          const hit = wire.calls.find((c) => c.method === "POST" && c.path === "/prompt-versions");
          expect(hit).toBeDefined();
          return hit!;
        },
        { timeout: 8_000 },
      );
      const body = save.body as Record<string, unknown>;
      expect(body.botId).toBe(BOT);
      expect(body.prompt).toBe(`${live.prompt}\nEdited in the pin.`);
      expect(body.label).toBe("v1.6");
      expect(body.persona).toEqual(live.persona);
      expect(body.voice).toEqual(live.voice);
      expect(body.guardrails).toEqual(live.guardrails);
      expect(body.agentCard).toEqual(live.agentCard);
      expect(body.summary).toBe("draft autosave");
      // one draft for one edit -- the debounce does not fork a second one
      await new Promise((r) => setTimeout(r, 1_500));
      expect(
        wire.calls.filter((c) => c.method === "POST" && c.path === "/prompt-versions"),
      ).toHaveLength(1);
    },
  );
});
