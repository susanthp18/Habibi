// @vitest-environment jsdom
/**
 * The property this control exists for: **only a full traverse confirms.**
 *
 * It replaced four typed-word gates ("type PUBLISH", "type PROMOTE", "type
 * DELETE", "type LANGUAGE"), and what those bought was not the word — it was
 * that no single stray keystroke or misplaced click could publish to production
 * or hard-delete a corpus. If a click on the track, an Enter on the focused
 * handle, or a drag the operator changed their mind about halfway can fire
 * `onConfirm`, this is a worse control than the Input it replaced, not a nicer
 * one.
 *
 * The keyboard path is tested as carefully as the pointer one, because a
 * drag-only commit is a commit that locks out every keyboard and switch user —
 * and the typed gate it replaced did not.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import "@/test/jsdom";

import { SlideToConfirm } from "./slide-to-confirm";

/** jsdom has no layout: every box is 0x0, so the drag maths has nothing to
 *  divide by. Give the track a size the way a browser would. */
function sizeTrack(track: HTMLElement, width = 300, height = 40) {
  track.getBoundingClientRect = () =>
    ({ width, height, left: 0, top: 0, right: width, bottom: height, x: 0, y: 0 }) as DOMRect;
}

function setup(props: Partial<Parameters<typeof SlideToConfirm>[0]> = {}) {
  const onConfirm = vi.fn();
  const view = render(<SlideToConfirm label="Slide to publish" onConfirm={onConfirm} {...props} />);
  const handle = screen.getByRole("slider", { name: "Slide to publish" });
  const track = handle.parentElement as HTMLElement;
  sizeTrack(track);
  return { onConfirm, handle, track, view };
}

/** The whole gesture: press the handle, travel, let go. */
function slide(handle: HTMLElement, track: HTMLElement, to: number) {
  fireEvent.pointerDown(handle, { pointerId: 1, clientX: 20 });
  // The first move only takes the grab offset — see the comment on `grab`.
  fireEvent.pointerMove(track, { pointerId: 1, clientX: 20 });
  fireEvent.pointerMove(track, { pointerId: 1, clientX: to });
  fireEvent.pointerUp(track, { pointerId: 1, clientX: to });
}

describe("SlideToConfirm", () => {
  it("confirms when the handle is dragged the whole way", () => {
    const { onConfirm, handle, track } = setup();

    slide(handle, track, 400); // past the right edge; the handle clamps
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(handle).toHaveAttribute("aria-valuenow", "100");
  });

  it("springs back when the drag is released short of the end", () => {
    const { onConfirm, handle, track } = setup();

    slide(handle, track, 150); // half way
    expect(onConfirm).not.toHaveBeenCalled();
    expect(handle).toHaveAttribute("aria-valuenow", "0");
  });

  it("ignores the keys every other focused control answers to", () => {
    const { onConfirm, handle } = setup();

    fireEvent.keyDown(handle, { key: "Enter" });
    fireEvent.keyDown(handle, { key: " " });
    fireEvent.click(handle);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("confirms from the keyboard, but only at the end of the travel", () => {
    const { onConfirm, handle } = setup();

    for (let i = 0; i < 5; i++) fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(handle).toHaveAttribute("aria-valuenow", "50");

    fireEvent.keyDown(handle, { key: "End" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("cannot be slid twice, so a slow action is not confirmed again", () => {
    const { onConfirm, handle, track } = setup();

    slide(handle, track, 400);
    slide(handle, track, 400);
    fireEvent.keyDown(handle, { key: "End" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("does not confirm while disabled, and leaves the focus ring out of reach", () => {
    const { onConfirm, handle, track } = setup({ disabled: true });

    slide(handle, track, 400);
    fireEvent.keyDown(handle, { key: "End" });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(handle).toHaveAttribute("tabindex", "-1");
  });

  it("returns to the start when the action it fired comes back failed", () => {
    // busy true -> false with the dialog still open is the failure shape. A
    // slider left spent there is a retry the operator cannot reach.
    const onConfirm = vi.fn();
    const { rerender } = render(
      <SlideToConfirm label="Slide to publish" onConfirm={onConfirm} busy />,
    );
    rerender(<SlideToConfirm label="Slide to publish" onConfirm={onConfirm} busy={false} />);

    const handle = screen.getByRole("slider", { name: "Slide to publish" });
    expect(handle).toHaveAttribute("aria-valuenow", "0");

    const track = handle.parentElement as HTMLElement;
    sizeTrack(track);
    slide(handle, track, 400);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
