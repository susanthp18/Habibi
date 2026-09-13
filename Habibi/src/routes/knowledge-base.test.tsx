// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The knowledge base, rendered against the wire.
//
// The pin under which the route's twenty-three pieces of state become one
// reducer: the real page, the real api/kb.ts, fetch answered from the samples.
// It asserts the documents an operator sees and what disabling one sends.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { KbDocument } from "@/api/kb";
import { mountAt } from "@/test/mount";
import { installWireFetch, sample, type WireCall } from "@/test/wire-fetch";

const { KnowledgeBasePage } = await import("./_app.knowledge-base.lazy");

const docs = sample<KbDocument[]>("GET /kb/documents");
const enabledDoc = docs.find((d) => d.enabled)!;

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    "PATCH /kb/documents/{id}": (call: WireCall) => ({
      document: { ...enabledDoc, ...(call.body as object) },
      jobId: null,
    }),
  });
});

afterEach(() => {
  wire.restore();
});

const mount = () =>
  mountAt("/knowledge-base", <KnowledgeBasePage search={{}} />, {
    validateSearch: (search) =>
      search as { gapId?: string; q?: string; tab?: "documents" | "faqs" | "gaps" | "test" },
  });

describe("/knowledge-base", () => {
  it("lists the documents the API serves", { timeout: 30_000 }, async () => {
    mount();
    for (const d of docs) {
      expect((await screen.findAllByText(d.title, {}, { timeout: 15_000 })).length).toBeGreaterThan(
        0,
      );
    }
    expect(wire.calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("disabling a document sends exactly that", { timeout: 30_000 }, async () => {
    mount();
    const toggle = await screen.findByRole(
      "switch",
      { name: `Enable ${enabledDoc.title}` },
      { timeout: 15_000 },
    );
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    const patch = await waitFor(
      () => {
        const hit = wire.calls.find(
          (c) => c.method === "PATCH" && c.path === `/kb/documents/${enabledDoc.id}`,
        );
        expect(hit).toBeDefined();
        return hit!;
      },
      { timeout: 8_000 },
    );
    expect(patch.body).toEqual({ enabled: false });
  });
});
