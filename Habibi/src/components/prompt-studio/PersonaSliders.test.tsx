// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The language controls keep the stored persona consistent.
//
// The chips hide the primary language, but the stored fallback list used to
// keep it: a card that moved from Hindi to English still declared Hindi as its
// own fallback, and the recogniser was handed a fallback equal to its primary.
// -----------------------------------------------------------------------------
import "@/test/jsdom";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PersonaState } from "@/api/types/prompt-studio";
import { DEFAULT_PERSONA } from "@/data/prompt-studio-seed";

vi.mock("@/api/prompt-studio", () => ({ previewTts: vi.fn() }));

const { PersonaSliders } = await import("./PersonaSliders");

function renderWith(value: PersonaState) {
  const onChange = vi.fn();
  render(
    <PersonaSliders
      value={value}
      onChange={onChange}
      presets={[]}
      onApplyPreset={() => undefined}
      voice={{} as never}
    />,
  );
  return onChange;
}

describe("PersonaSliders languages", () => {
  it("removes the new primary from the fallback list", () => {
    const onChange = renderWith({
      ...DEFAULT_PERSONA,
      language: "English",
      fallbackLanguages: ["Hindi", "Tamil"],
    });
    fireEvent.change(screen.getByLabelText("Primary language"), { target: { value: "Hindi" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as PersonaState;
    expect(next.language).toBe("Hindi");
    expect(next.fallbackLanguages).toEqual(["Tamil"]);
  });

  it("chips are buttons that announce their state", () => {
    renderWith({ ...DEFAULT_PERSONA, language: "English", fallbackLanguages: ["Hindi"] });
    const hindi = screen.getByRole("button", { name: "Hindi", pressed: true });
    expect(hindi.getAttribute("type")).toBe("button");
  });
});
