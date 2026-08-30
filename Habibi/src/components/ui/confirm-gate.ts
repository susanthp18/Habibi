/**
 * The promise half of `useConfirm`, with no React and no DOM in it.
 *
 * Extracted so the property that actually matters can be tested: **an
 * unanswered dialog must never read as consent.** Every path that is not an
 * explicit confirm — cancel, Escape, the overlay, a second question arriving,
 * the component unmounting — has to resolve `false`, and a promise that is
 * never settled at all is worse than either answer because it hangs the handler
 * awaiting it.
 *
 * This repo's vitest config is `environment: "node"` on the stated grounds that
 * "a test environment the tests do not use is a dependency that can only
 * break". Pulling the logic out here keeps that true rather than adding jsdom to
 * test four lines of bookkeeping.
 */
export type ConfirmGate = {
  /** Begin asking. Any question already open is abandoned as `false`. */
  ask(): Promise<boolean>;
  /** Answer the open question. Second and later calls are no-ops. */
  settle(confirmed: boolean): void;
  /** True while a question is awaiting an answer. */
  readonly pending: boolean;
};

export function createConfirmGate(): ConfirmGate {
  let resolver: ((ok: boolean) => void) | null = null;
  return {
    ask() {
      // Abandoning the previous question as `false` rather than dropping it:
      // a stranded promise is an `await` that never returns, which freezes the
      // handler holding it with no error and no way to tell from the outside.
      resolver?.(false);
      return new Promise<boolean>((resolve) => {
        resolver = resolve;
      });
    },
    settle(confirmed: boolean) {
      // Radix can deliver both an action click and a close for one dismissal.
      // Clearing before resolving makes the second delivery a no-op instead of
      // depending on which order they arrive in.
      const resolve = resolver;
      resolver = null;
      resolve?.(confirmed);
    },
    get pending() {
      return resolver !== null;
    },
  };
}
