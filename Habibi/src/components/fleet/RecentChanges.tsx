import { useEffect, useId, useState } from "react";
import { useChangeLog } from "@/api/agent-studio";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { changeVerb, parseLogTimestamp, actorLabel } from "@/lib/change-log-actions";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Whether the change log is open, remembered across visits.
 *
 * Read in an effect and never during render: the server has no localStorage,
 * so a value read on the way to the first paint is a hydration mismatch. The
 * sidebar's collapse preference solved this the same way — render the default,
 * then restore.
 */
const CHANGE_LOG_OPEN_KEY = "bigbound.agent-studio.change-log-open";

function readChangeLogOpen(): boolean {
  try {
    return window.localStorage.getItem(CHANGE_LOG_OPEN_KEY) === "1";
  } catch {
    // Private mode, or storage disabled. Closed is the safe default.
    return false;
  }
}

function writeChangeLogOpen(next: boolean): void {
  try {
    window.localStorage.setItem(CHANGE_LOG_OPEN_KEY, next ? "1" : "0");
  } catch {
    // A preference that cannot be saved is not worth failing a click over.
  }
}

/**
 * Who changed what an agent says, and when. GET /agent-studio/change-log had
 * no caller at all, so this was previously reachable only by curl.
 *
 * The log is hash-chained server-side and the response carries a verdict over
 * the whole chain. A broken chain means an entry was rewritten or removed —
 * the one thing an audit log exists to make visible — so it is rendered as an
 * error rather than left to the absence of a row nobody would notice.
 */
export function RecentChanges() {
  // Tenant-wide, so no botId. Note chain.checked is tenant-scoped whether or
  // not entries are filtered — see the note on fetchChangeLog.
  const { data, isLoading, isError, error, refetch, isFetching } = useChangeLog(undefined, 10);
  const entries = data?.entries ?? [];
  const chain = data?.chain;
  // Newest first — read_entries orders by the chain's own seq, descending.
  const latest = entries[0];

  // Closed on first paint, always, for two reasons and the second is the one
  // that matters.
  //
  // It is the state that leaves the roster any room. This section is a
  // non-shrinking sibling of the card grid, so it takes its height first: 317px
  // of a 747px column, which left 3.2 of 9 cards reachable on a 1440x900
  // laptop. Nine cards behind a scrollbar, under a log almost nobody reads on
  // every visit.
  //
  // And it is the only state whose height does not change when the request
  // lands. `if (isLoading) return null` used to render nothing, then 317px,
  // and every card jumped up a third of a screen on load.
  const [open, setOpen] = useState(false);
  const panelId = useId();
  useEffect(() => {
    setOpen(readChangeLogOpen());
  }, []);
  const toggle = () =>
    setOpen((prev) => {
      writeChangeLogOpen(!prev);
      return !prev;
    });

  // Collapsing the rows must not collapse the verdict. The log is hash-chained
  // server-side and a broken chain means an entry was rewritten or removed —
  // the one thing an audit log exists to make visible — so it belongs in the
  // header, where a closed panel still shows it.
  const verdict = isError ? (
    <Lozenge tone="danger">could not be read</Lozenge>
  ) : isLoading ? (
    <span className="text-body-small text-text-subtlest">checking…</span>
  ) : chain && !chain.ok ? (
    <Lozenge
      tone="danger"
      title={`The audit chain does not verify${chain.brokenAt ? ` at ${chain.brokenAt}` : ""}. An entry has been rewritten or removed.`}
    >
      audit chain broken{chain.reason ? ` · ${chain.reason}` : ""}
    </Lozenge>
  ) : chain ? (
    <Lozenge tone="neutral" title="Every entry hashes to its predecessor.">
      chain verified · {chain.checked}
    </Lozenge>
  ) : null;

  return (
    <section className="shrink-0 border-t border-border bg-surface">
      <div className="flex flex-wrap items-center gap-100 pr-400">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={panelId}
          className="focus-ring flex flex-1 flex-wrap items-center gap-100 px-400 py-150 text-left hover:bg-surface-sunken"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 text-text-subtlest" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-text-subtlest" />
          )}
          <span className="text-body font-semibold">Recent changes</span>
          {verdict}
          {!open && !isLoading && !isError ? (
            // The newest entry, not a count. A count next to `chain verified ·
            // 7` is two different sevens side by side — one is every entry in
            // the tenant, the other is how many this request asked for — and
            // neither answers the question someone glances at a change log to
            // ask, which is whether anything moved recently and who moved it.
            <span className="truncate text-body-small text-text-subtle">
              {latest
                ? `${actorLabel(latest.actorUserId)} ${changeVerb(latest.action)} ${latest.botId}${
                    parseLogTimestamp(latest.at)
                      ? ` · ${parseLogTimestamp(latest.at)!.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
                      : ""
                  }`
                : "nothing published, rolled back, archived or restored yet"}
            </span>
          ) : null}
        </button>
        {isError ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            loading={isFetching}
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            Retry
          </Button>
        ) : null}
      </div>

      {/* An error shows whether or not the panel is open. An audit log that
          removes itself when its request fails is worse than one that is down:
          the screen looks the same as a tenant that has never published, so
          nobody goes looking. Requiring a click to find that out is the same
          failure with an extra step. */}
      {open || isError ? (
        <div
          id={panelId}
          className="max-h-[14rem] overflow-y-auto border-t border-border px-400 py-150"
        >
          {isError ? (
            <p className="text-body-small text-text-danger">
              The change log could not be read, so this is not a record of nothing happening — it is
              a record that could not be shown.{" "}
              {error instanceof Error ? error.message : "Request failed"}
            </p>
          ) : entries.length === 0 ? (
            <p className="text-body-small text-text-subtle">
              Nothing published, rolled back, archived or restored yet.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {entries.map((entry) => (
                <li key={entry.id} className="flex flex-wrap items-baseline gap-100 py-100">
                  <span className="text-body-small font-medium">
                    {actorLabel(entry.actorUserId)}
                  </span>
                  <span className="text-body-small text-text-subtle">
                    {changeVerb(entry.action)}
                  </span>
                  <span className="font-mono text-body-tiny text-text-subtle">{entry.botId}</span>
                  {entry.versionLabel ? (
                    <Lozenge tone="neutral">{entry.versionLabel}</Lozenge>
                  ) : null}
                  {entry.changed?.length ? (
                    <span
                      className="text-body-tiny text-text-subtlest"
                      title="Components that differ from the version before it"
                    >
                      {entry.changed.join(", ")}
                    </span>
                  ) : null}
                  <span className="ml-auto text-body-tiny text-text-subtlest">
                    {parseLogTimestamp(entry.at)?.toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    }) ?? "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}
