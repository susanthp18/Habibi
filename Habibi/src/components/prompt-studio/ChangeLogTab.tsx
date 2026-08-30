// -----------------------------------------------------------------------------
// The tamper-evident agent change log — GET /agent-studio/change-log.
//
// Distinct from the "History" sheet in the header, which lists prompt VERSIONS.
// This is the audit trail: who changed what an agent says, when, and what the
// compiler said at the time — hash-chained, so a rewritten or deleted historical
// entry is visible rather than merely absent. In a bank deployment it is the
// first artefact an auditor asks for, and until now it was a curl command.
//
// Two things this screen must not do.
//
// A broken chain cannot be understated. It means somebody altered or removed a
// record after the fact, so it gets danger styling and names the reason and the
// row, rather than a subtle grey note nobody reads.
//
// And an empty list is not a verdict. The chain is scoped to the TENANT while
// `entries` is filtered by card, so a card that has never been published shows
// zero entries beside a chain that walked every other card's rows. Saying
// "verified" over an empty table would let "no changes" and "someone deleted
// the changes" look identical — the exact distinction the endpoint exists to
// draw.
// -----------------------------------------------------------------------------

import { AlertCircle, ShieldAlert, ShieldCheck } from "lucide-react";

import { useChangeLog, type ChainVerdict, type ChangeLogEntry } from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { partitionGates } from "@/lib/gate-status";

// `agent.restore` was missing from both maps although the backend has recorded
// it since `record_restore` landed, so a restore rendered as the raw string
// "agent.restore" in a neutral chip — the one screen an auditor reads, spelling
// an action in wire format because nobody added the row.
const ACTION_LABEL: Record<string, string> = {
  "agent.publish": "Published",
  "agent.rollback": "Rolled back",
  "agent.archive": "Archived",
  "agent.restore": "Restored",
};

const ACTION_TONE: Record<string, LozengeTone> = {
  "agent.publish": "success",
  "agent.rollback": "warning",
  "agent.archive": "neutral",
  "agent.restore": "information",
};

const CHAIN_REASON: Record<string, string> = {
  prev_hash_mismatch: "a link does not point at the entry before it",
  entry_hash_mismatch: "an entry's contents no longer match its own hash",
};

function stamp(at: string | null): string {
  if (!at) return "—";
  const ms = Date.parse(at.replace(" ", "T"));
  if (Number.isNaN(ms)) return at;
  return new Date(ms).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

function ChainBanner({ chain, entryCount }: { chain: ChainVerdict; entryCount: number }) {
  if (!chain.ok) {
    return (
      <div className="rounded-medium border border-border-danger bg-background-danger-subtler px-150 py-150">
        <div className="flex items-center gap-075">
          <ShieldAlert className="h-4 w-4 shrink-0 text-text-danger-bolder" />
          <span className="text-body font-semibold text-text-danger-bolder">
            Chain BROKEN — this change log has been tampered with
          </span>
        </div>
        <p className="mt-050 text-body-small leading-relaxed text-text-danger-bolder">
          {CHAIN_REASON[chain.reason ?? ""] ?? chain.reason ?? "the chain did not verify"}. The
          first bad link is <code className="font-mono">{chain.brokenAt ?? "unknown"}</code>, found
          while walking {chain.checked} {chain.checked === 1 ? "entry" : "entries"}. Entries at or
          after it cannot be trusted. Treat this as an integrity incident, not a display problem.
        </p>
      </div>
    );
  }
  if (chain.checked === 0) {
    return (
      <div className="rounded-medium border border-border bg-surface px-150 py-150">
        <div className="flex items-center gap-075">
          <ShieldCheck className="h-4 w-4 shrink-0 text-text-subtle" />
          <span className="text-body font-medium text-text">Nothing recorded yet</span>
        </div>
        <p className="mt-050 text-body-small text-text-subtle">
          No agent has been published, rolled back or archived in this tenant, so there is no chain
          to verify. This is not the same as a verified empty log.
        </p>
      </div>
    );
  }
  return (
    <div className="rounded-medium border border-border-success bg-background-success-subtler px-150 py-150">
      <div className="flex items-center gap-075">
        <ShieldCheck className="h-4 w-4 shrink-0 text-text-success-bolder" />
        <span className="text-body font-medium text-text-success-bolder">Chain intact</span>
      </div>
      <p className="mt-050 text-body-small text-text-success-bolder">
        {chain.checked} {chain.checked === 1 ? "entry" : "entries"} verified across the tenant
        {entryCount === 0 ? " — none of them on this card" : ""}. Every link points at the entry
        before it and every entry still hashes to its recorded value.
      </p>
    </div>
  );
}

function EntryRow({ entry }: { entry: ChangeLogEntry }) {
  // `warn` is not `fail`. This used to bucket everything that was neither
  // "pass" nor "skipped" as a failure and print it in red as "gates failed",
  // which turned a G10 warning — a verdict the compiler issues on publishes it
  // deliberately allows — into a permanent record saying the publish failed
  // its gates. Wrong verdicts on the tamper-evidence screen are the one class
  // of bug this screen cannot have.
  const { failed, warned, total: gateCount } = partitionGates(entry.gates ?? {});
  return (
    <li className="border-b border-border px-150 py-150 last:border-b-0">
      <div className="flex flex-wrap items-center gap-100">
        <Lozenge tone={ACTION_TONE[entry.action] ?? "neutral"}>
          {ACTION_LABEL[entry.action] ?? entry.action}
        </Lozenge>
        {entry.versionLabel && (
          <span className="font-mono text-body-small text-text">
            {entry.previousVersionLabel ? `${entry.previousVersionLabel} → ` : ""}
            {entry.versionLabel}
          </span>
        )}
        <span className="text-body-small text-text-subtle">{entry.actorUserId ?? "unknown"}</span>
        <span className="ml-auto text-body-small text-text-subtlest">{stamp(entry.at)}</span>
      </div>
      {entry.summary && <p className="mt-050 text-body-small text-text-subtle">{entry.summary}</p>}
      <div className="mt-075 flex flex-wrap items-center gap-075 text-body-tiny">
        {(entry.changed ?? []).map((c) => (
          <span
            key={c}
            className="rounded-small border border-border bg-surface-sunken px-075 py-025 font-mono text-text-subtle"
          >
            {c}
          </span>
        ))}
        {entry.rollout && (
          <span className="text-text-subtlest">
            {entry.rollout.shadow ? "shadow" : `${entry.rollout.trafficPct}% traffic`}
            {entry.rollout.autoRollback.length > 0 &&
              ` · auto-rollback on ${entry.rollout.autoRollback.join(", ")}`}
          </span>
        )}
        {gateCount > 0 && (
          <span
            className={
              failed.length > 0
                ? "text-text-danger"
                : warned.length > 0
                  ? "text-text-warning-bolder"
                  : "text-text-subtlest"
            }
          >
            {failed.length > 0
              ? `gates failed: ${failed.join(", ")}`
              : warned.length > 0
                ? `gates warned: ${warned.join(", ")}`
                : `${gateCount} gates recorded`}
          </span>
        )}
        {entry.entryHash && (
          <code className="ml-auto font-mono text-text-subtlest" title={entry.entryHash}>
            {entry.entryHash.slice(0, 12)}…
          </code>
        )}
      </div>
    </li>
  );
}

export function ChangeLogTab({ botId }: { botId: string }) {
  const { data, isPending, isError, error } = useChangeLog(botId);

  if (isPending) {
    return (
      <div className="px-150 py-200">
        <LoadingState label="Loading change log" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-start gap-100 rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
        <AlertCircle className="mt-025 h-4 w-4 shrink-0" />
        <span>
          Change log unavailable — chain integrity cannot be confirmed, so treat it as unverified
          rather than intact. {(error as Error)?.message ?? ""}
        </span>
      </div>
    );
  }

  const entries = data?.entries ?? [];
  const chain = data?.chain ?? { ok: false, checked: 0, brokenAt: null, reason: "no_verdict" };

  return (
    <div className="space-y-150">
      <div>
        <h2 className="text-body font-semibold text-text">Change log</h2>
        <p className="mt-025 max-w-prose text-body-small text-text-subtle">
          Who changed what this agent says, and what the compiler said at the time. Hash-chained
          across the tenant, so a removed or rewritten entry shows up as a break rather than as an
          absence.
        </p>
      </div>

      <ChainBanner chain={chain} entryCount={entries.length} />

      {entries.length === 0 ? (
        <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-250 text-center">
          <div className="text-body font-medium text-text">No entries for this card</div>
          <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">
            This card has never been published, rolled back or archived. The chain verdict above is
            tenant-wide and covers other cards.
          </p>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-medium border border-border bg-surface">
          {entries.map((entry) => (
            <EntryRow key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  );
}
