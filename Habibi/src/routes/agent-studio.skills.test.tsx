// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The two skills screens, rendered against the wire (SKILLS-17).
//
// The roster lists what `/agent-studio/skills` serves and refuses to create a
// skill with no description before anything is sent; the editor shows the row
// `/agent-studio/skills/{id}` serves and a save sends one PATCH carrying the
// edited body. Nothing here names a hook.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { mountAt } from "@/test/mount";
import { installWireFetch, sample, type WireCall } from "@/test/wire-fetch";

const { SkillsIndexPage } = await import("./_app.agent-studio.skills.index");
const { SkillEditorPage } = await import("./_app.agent-studio.skills.$skillId");

type SkillRow = { id: string; slug: string; description: string; body: string };
const skills = sample<SkillRow[]>("GET /agent-studio/skills");
const detail = sample<SkillRow>("GET /agent-studio/skills/{skill_id}");

let wire: ReturnType<typeof installWireFetch>;

beforeEach(() => {
  wire = installWireFetch({
    "PATCH /agent-studio/skills/{skill_id}": (call: WireCall) => ({
      ...detail,
      ...(call.body as object),
      version: "2",
    }),
  });
});

afterEach(() => {
  wire.restore();
});

describe("/agent-studio/skills", () => {
  it("lists every skill the API serves", async () => {
    mountAt("/agent-studio/skills", <SkillsIndexPage />);
    for (const s of skills) await screen.findByText(s.slug);
    expect(wire.calls.filter((c) => c.method !== "GET")).toEqual([]);
  });

  it("refuses a new skill with no description before sending anything", async () => {
    mountAt("/agent-studio/skills", <SkillsIndexPage />);
    await screen.findByText(skills[0]!.slug);
    fireEvent.click(screen.getByRole("button", { name: /New skill/ }));
    const name = screen.getByPlaceholderText("Premium lapse chase");
    fireEvent.change(name, { target: { value: "Lapse rescue" } });
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() => expect(screen.getByText(/Description is required/)).toBeInTheDocument());
    expect(wire.calls.filter((c) => c.method === "POST")).toEqual([]);
    // the typed name survives the refusal
    expect((name as HTMLInputElement).value).toBe("Lapse rescue");
  });
});

describe("/agent-studio/skills/$skillId", () => {
  it("shows the skill and saves an edited body as one PATCH", async () => {
    mountAt("/agent-studio/skills/$skillId", <SkillEditorPage skillId={detail.id} />, {
      entry: `/agent-studio/skills/${detail.id}`,
    });
    const body = await waitFor(() => {
      const area = Array.from(document.querySelectorAll("textarea")).find(
        (t) => t.value === detail.body,
      );
      expect(area).toBeDefined();
      return area!;
    });
    expect(screen.getAllByText(detail.slug).length).toBeGreaterThan(0);
    fireEvent.change(body, { target: { value: `${detail.body}\n\n4. Edited in the pin.` } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    const patch = await waitFor(() => {
      const hit = wire.calls.find((c) => c.method === "PATCH");
      expect(hit).toBeDefined();
      return hit!;
    });
    expect(patch.path).toBe(`/agent-studio/skills/${detail.id}`);
    expect((patch.body as { body: string }).body).toContain("Edited in the pin.");
    expect(wire.calls.filter((c) => c.method === "PATCH")).toHaveLength(1);
  });
});
