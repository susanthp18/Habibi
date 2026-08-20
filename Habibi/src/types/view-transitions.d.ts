/** View Transitions API — not yet in this TypeScript DOM lib. */
interface ViewTransition {
  readonly ready: Promise<void>;
  readonly finished: Promise<void>;
  readonly updateCallbackDone: Promise<void>;
  skipTransition(): void;
}

interface Document {
  startViewTransition(updateCallback?: () => void | Promise<void>): ViewTransition;
}

interface KeyframeAnimationOptions {
  pseudoElement?: string;
}
