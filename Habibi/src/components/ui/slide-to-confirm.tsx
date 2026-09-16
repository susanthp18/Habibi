import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Check, ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A commit that takes a gesture, replacing "type PUBLISH to confirm".
 *
 * The typed word was never really about the word. It is a *deliberateness* gate:
 * something that a stray Enter on a focused button cannot produce. Typing buys
 * that at a bad price — it is eight keystrokes on a control the operator already
 * meant to press, it reads as a punishment, and the four gates in this app had
 * already drifted apart on how they matched (`text !== "PROMOTE"` raw and
 * case-sensitive in the sandbox, `.trim().toUpperCase()` in the KB, and
 * PublishDialog carrying a comment about having fixed exactly that mismatch
 * between its own two fields).
 *
 * A slide is the same gate — it cannot happen by accident, and it cannot happen
 * without the pointer travelling the whole control — at the price of one motion.
 * It is also the commit itself, not a key to a second button: sliding publishes.
 * A gate that unlocks a button restores the accidental click it was there to
 * prevent.
 *
 * **No animation library.** The reference implementation for this pattern wants
 * framer-motion; the morph below is `left` and `width` moving together under one
 * CSS transition, which is the same picture, and the global
 * `prefers-reduced-motion` rule in styles.css already turns it off for anyone
 * who asked. A dependency for one component's easing is not worth its bundle.
 */
type Props = {
  /** The instruction, and the control's accessible name. "Slide to publish". */
  label: string;
  /** What it says once it has been slid. Defaults to the label. */
  confirmedLabel?: string;
  onConfirm: () => void;
  disabled?: boolean;
  /**
   * The action is in flight. Also the reset signal: when it goes back to false
   * with this still mounted, the action failed and the dialog is still open, so
   * the slider returns to the start rather than sitting spent with no way to
   * retry short of closing the dialog.
   */
  busy?: boolean;
  /** Danger surfaces (purges, deletes) fill red instead of brand blue. */
  tone?: "brand" | "danger";
  /** Landed on the slider itself, so `bindControlId` / `htmlFor` reach it. */
  id?: string;
  className?: string;
};

/** How far across counts as "let go at the end" rather than "gave up". */
const THRESHOLD = 0.92;
/** One arrow key. Ten presses cross it, which is the keyboard's deliberateness. */
const STEP = 0.1;
/** The handle is a square of the track's height — `--space-500`, 2.5rem. */
const HANDLE = "var(--space-500)";

const clamp = (n: number) => Math.min(1, Math.max(0, n));

export function SlideToConfirm({
  label,
  confirmedLabel,
  onConfirm,
  disabled = false,
  busy = false,
  tone = "brand",
  id,
  className,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  /**
   * Where in the handle the pointer took hold, in px from the track's left
   * edge — and it is taken at the FIRST MOVE, never at the press.
   *
   * Deciding it on pointerdown is what makes a slider teleport: a press on the
   * track away from the handle would set the offset to the handle's own middle,
   * and the first move would jump the handle the whole way in one frame — which
   * is a confirm the operator did not make.
   */
  const grab = useRef<number | null>(null);
  const [pct, setPct] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [done, setDone] = useState(false);

  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) {
      setDone(false);
      setPct(0);
    }
    wasBusy.current = busy;
  }, [busy]);

  /** Track width minus the handle: the distance the handle can actually move. */
  const travel = () => {
    const box = trackRef.current?.getBoundingClientRect();
    return box ? Math.max(0, box.width - box.height) : 0;
  };

  const settle = (at: number) => {
    if (at < THRESHOLD) {
      setPct(0);
      return;
    }
    setPct(1);
    setDone(true);
    onConfirm();
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled || done) return;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    grab.current = null;
    setDragging(true);
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const span = travel();
    if (span <= 0) return;
    const at = e.clientX - (trackRef.current?.getBoundingClientRect().left ?? 0);
    if (grab.current === null) {
      grab.current = at - pct * span;
      return;
    }
    setPct(clamp((at - grab.current) / span));
  };

  const endDrag = () => {
    if (!dragging) return;
    setDragging(false);
    grab.current = null;
    settle(pct);
  };

  /**
   * Arrows, Home and End. Enter and Space deliberately do nothing: a confirm
   * that answers to the key every focused control answers to is the accident
   * this whole component exists to refuse. End is the keyboard's whole-travel
   * gesture — one key, but not one anybody hits by mistake.
   */
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (disabled || done) return;
    const next =
      e.key === "ArrowRight" || e.key === "ArrowUp"
        ? pct + STEP
        : e.key === "ArrowLeft" || e.key === "ArrowDown"
          ? pct - STEP
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? 1
              : null;
    if (next === null) return;
    e.preventDefault();
    const value = clamp(next);
    if (value >= 1) settle(1);
    else setPct(value);
  };

  const finished = confirmedLabel ?? label;

  return (
    <div
      ref={trackRef}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      className={cn(
        "relative h-500 w-full touch-none overflow-hidden rounded-full bg-surface-sunken ring-1 ring-border",
        disabled && "opacity-50",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 flex select-none items-center justify-center pl-500 text-body-small font-semibold text-text-subtlest",
          done && "invisible",
        )}
      >
        {label}
      </span>
      <div
        id={id}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct * 100)}
        aria-valuetext={done ? finished : label}
        aria-disabled={disabled || undefined}
        onPointerDown={onPointerDown}
        onKeyDown={onKeyDown}
        style={{
          width: done ? "100%" : HANDLE,
          left: done ? 0 : `calc(${pct} * (100% - ${HANDLE}))`,
        }}
        className={cn(
          // The morph, not a hand-over: `left` and `width` change by the same
          // amount, so the handle's right edge is stationary and it opens out
          // behind itself to fill the track it crossed. A scale would have
          // dragged the corner radius with it.
          "absolute top-0 flex h-full select-none items-center justify-center gap-075 rounded-full text-body-small font-semibold text-text-inverse focus-ring",
          tone === "danger" ? "bg-background-danger-bold" : "bg-background-brand-bold",
          // Never while dragging: a transition there is a handle that lags the
          // finger, which reads as the control being broken.
          !dragging && "transition-all duration-token-medium ease-token-out-practical",
          disabled ? "cursor-not-allowed" : done ? "cursor-default" : "cursor-grab",
        )}
      >
        {done ? (
          <>
            <Check aria-hidden className="size-4" />
            {finished}
          </>
        ) : (
          <ChevronRight aria-hidden className="size-4" />
        )}
      </div>
    </div>
  );
}
