// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The call sandbox, rendered against the wire.
//
// The pin under which the route's session state -- turns, script cursor, run,
// halt, flow cursor, tool calls -- becomes one reducer. The real page, the real
// api/sandbox.ts, fetch answered from the samples; it asserts the opening the
// operator sees and what "Next" sends: a run for this card's published version
// and this scenario, then the scripted customer line with the history so far.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Scenario } from "@/api/types/sandbox";
import type { PromptVersion } from "@/api/types/prompt-studio";
import { installWireFetch, sample, type WireCall } from "@/test/wire-fetch";

const { SandboxPage } = await import("./_app.sandbox.lazy");

const BOT = "kaia-v2-4";
const versions = sample<PromptVersion[]>("GET /prompt-versions");
const live = versions.find((v) => v.botId === BOT && v.status === "published")!;
const scenario = sample<Scenario[]>("GET /sandbox/scenarios")[0]!;

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    "GET /prompt-versions": (call: WireCall) => {
      const bot = new URLSearchParams(call.search).get("botId");
      return bot ? versions.filter((v) => v.botId === bot) : versions;
    },
    "GET /voice/status": {
      ok: false,
      detail: "no voice worker in a test",
      webrtcUrl: null,
      capacity: null,
    },
    "POST /sandbox/runs": (call: WireCall) => ({
      id: "SBX-pin",
      promptVersionId: (call.body as { promptVersionId: string }).promptVersionId,
      scenarioId: (call.body as { scenarioId: string }).scenarioId,
      kbSnapshotId: null,
      deploymentId: null,
      status: "running",
      openingMessage: null,
      promptVersion: live,
      context: {},
      turnBudget: 3,
    }),
    "POST /sandbox/runs/{run_id}/turns": (call: WireCall) => {
      const body = call.body as { text: string };
      return {
        runId: "SBX-pin",
        promptVersionId: live.id,
        nodeKey: null,
        customerTurn: {
          id: "t-c-1",
          role: "customer",
          text: body.text,
          intent: "waiver_request",
          intentScores: { waiver_request: 0.9 },
          sentiment: -0.4,
          sentimentLabel: "negative",
        },
        botTurn: {
          id: "t-b-1",
          role: "bot",
          text: "I understand. Let me look at that fee.",
          chunkIds: [],
          chunks: [],
          latencyMs: 120,
          tokens: 40,
          guardrailFlags: [],
          intent: "waiver_request",
          sentiment: 0,
          sentimentLabel: "neutral",
          halted: false,
        },
      };
    },
  });
});

afterEach(() => {
  wire.restore();
});

function mount() {
  const rootRoute = createRootRoute({ component: Outlet });
  const route = createRoute({
    getParentRoute: () => rootRoute,
    path: "/sandbox",
    component: () => <SandboxPage search={{ botId: BOT }} />,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([route]),
    history: createMemoryHistory({ initialEntries: ["/sandbox"] }),
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("/sandbox", () => {
  it(
    "opens the first scenario with its opening line for the card's published version",
    { timeout: 30_000 },
    async () => {
      mount();
      await screen.findAllByText(new RegExp(scenario.title.slice(0, 20)), {}, { timeout: 15_000 });
      // the same substitutions the page makes before the run exists
      const opening = scenario
        .openingBot!.replaceAll("{customer_name}", scenario.persona.name)
        .replaceAll("{agent_name}", "Priya")
        .replaceAll("{bank_name}", "HDFC Bank")
        .replaceAll("{language}", scenario.persona.language)
        .slice(0, 40);
      expect(
        (
          await screen.findAllByText(
            new RegExp(opening.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
            {},
            { timeout: 10_000 },
          )
        ).length,
      ).toBeGreaterThan(0);
      expect(
        wire.calls.filter((c) => c.method === "POST" && c.path.startsWith("/sandbox")),
      ).toEqual([]);
    },
  );

  it(
    "Next creates the run for this version and scenario, then sends the scripted line",
    { timeout: 30_000 },
    async () => {
      mount();
      const next = await screen.findByRole("button", { name: /^next$/i }, { timeout: 15_000 });
      await waitFor(() => expect(next).toBeEnabled(), { timeout: 10_000 });
      fireEvent.click(next);
      const run = await waitFor(
        () => {
          const hit = wire.calls.find((c) => c.method === "POST" && c.path === "/sandbox/runs");
          expect(hit).toBeDefined();
          return hit!;
        },
        { timeout: 8_000 },
      );
      expect(run.body).toMatchObject({
        promptVersionId: live.id,
        scenarioId: scenario.id,
        kbSnapshotId: null,
      });
      const turn = await waitFor(
        () => {
          const hit = wire.calls.find(
            (c) => c.method === "POST" && c.path === "/sandbox/runs/SBX-pin/turns",
          );
          expect(hit).toBeDefined();
          return hit!;
        },
        { timeout: 8_000 },
      );
      // the history the model sees starts with the opening the operator saw
      expect(turn.body).toMatchObject({
        text: scenario.turns[0]!.customer,
        nodeKey: null,
        history: [{ role: "bot", text: expect.stringContaining(scenario.persona.name) }],
      });
      // the reply lands in the transcript
      await screen.findByText("I understand. Let me look at that fee.", {}, { timeout: 8_000 });
    },
  );
});
