import { useEffect, useState } from "react";

/**
 * True while the viewport is at least `px` wide.
 *
 * Tailwind's responsive classes hide a pane but keep it in the layout tree,
 * which is fine until the pane is a child of SplitPanes — the wrapper still
 * claims its flex-basis percentage and leaves a gap where the hidden pane was.
 * Layouts that resize therefore have to make the breakpoint a real value and
 * not render the pane at all.
 */
export function useMinWidth(px: number): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(`(min-width: ${px}px)`).matches : true,
  );

  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${px}px)`);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [px]);

  return matches;
}
