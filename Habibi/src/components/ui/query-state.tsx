import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";

import { LoadingState } from "@/components/ui/loading-state";

/**
 * The three answers a list query can give, kept distinct.
 *
 * This codebase names "graceful degradation lies" as its #1 failure mode and
 * then reproduces it every time a panel reaches for `query.data ?? []` and
 * renders the empty case as a statement of fact. The shipped examples:
 *
 * - The Connectors tab told authors "No approved connectors. A connector has to
 *   be registered and approved…" and linked them off to Integrations, while the
 *   API had two approved connectors and had merely failed to answer. Business
 *   advice, generated from a network error, sending someone to fix a problem
 *   that does not exist.
 * - The Skills tab rendered `0 tok / 0 tok / 0 files` and asserted "Skill
 *   catalog is empty" — a false statement about the system, in numbers, which
 *   read exactly like a measured one.
 *
 * The distinction is not hard, it is just easy to skip, so this makes skipping
 * it the longer path: `empty` is only reached once the query has actually
 * succeeded.
 */
export function QueryState({
  query,
  label,
  empty,
  children,
}: {
  query: { isPending: boolean; isError: boolean; error?: unknown };
  /** Names the thing being loaded — "connectors", "the skill catalog". */
  label: string;
  /**
   * Rendered after `children`, but only once the query has actually succeeded.
   * Callers already gate this on `rows.length === 0`; the point of routing it
   * through here is that the gate can no longer be reached by a failure.
   */
  empty?: ReactNode;
  children: ReactNode;
}) {
  if (query.isPending) {
    return (
      <div className="rounded-medium border border-border p-150">
        <LoadingState label={`Loading ${label}`} />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="flex items-start gap-075 rounded-medium border border-border-danger bg-background-danger-subtler p-150 text-body-small text-text-danger-bolder">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <div>
          <div className="font-semibold">Could not load {label}</div>
          <p className="mt-025">
            {query.error instanceof Error ? query.error.message : "The API did not answer."} This is
            a failed read, not a statement about what exists.
          </p>
        </div>
      </div>
    );
  }
  return (
    <>
      {children}
      {empty}
    </>
  );
}
