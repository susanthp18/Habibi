import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import {
  useAgentStudioCards,
  useEvalReports,
  useAgentStudioTemplates,
  useArchiveAgentCard,
  useChangeLog,
  useCloneAgentCard,
  type AgentCardSummary,
  type EvalReport,
} from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { Bot } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";

export const Route = createFileRoute("/agent-studio/")({
  component: FleetIndex,
});

/**
 * Routing, not deployment. Every published card used to read "live · 100%",
 * which described its deployment row and said nothing about whether traffic
 * can reach it.
 *
 * The first fix over-corrected: it walked the graph from BOT_ID alone, so
 * Intake — a live front door at 100% traffic that routes *to* Collections —
 * read "unreachable" beside two empty scaffolds that genuinely are. A card
 * holding its own active deployment is addressable by bot_id, so it gets
 * `direct` and `unreachable` goes back to meaning dead config.
 */
const ROUTING: Record<
  AgentCardSummary["reachability"],
  { label: string; tone: LozengeTone; help: (entry: string) => string }
> = {
  entry: {
    label: "takes inbound",
    tone: "success",
    help: () => "Every inbound call and message resolves to this card.",
  },
  handoff: {
    label: "via handoff",
    tone: "information",
    help: (entry) => `Reached mid-conversation from ${entry}'s handoff allowlist.`,
  },
  direct: {
    label: "direct only",
    tone: "information",
    help: (entry) =>
      `Addressed directly by bot id — it has its own live deployment — but nothing hands off to it, including ${entry}.`,
  },
  unreachable: {
    label: "unreachable",
    tone: "warning",
    help: (entry) =>
      `Nothing routes here — no deployment of its own, and not on any allowlist from ${entry}.`,
  },
  archived: {
    label: "archived",
    tone: "neutral",
    help: () => "Retired. Kept for audit; takes no traffic.",
  },
};

/** Tolerates a reachability value this build does not know about. */
function routing(card: AgentCardSummary) {
  return ROUTING[card.reachability] ?? ROUTING.unreachable;
}

/**
 * The last few eval runs for one card, newest on the right.
 *
 * "evals: pass" is one bit about one run and says nothing about whether the
 * card has been getting better or worse. The reports are fetched once for the
 * whole fleet and grouped here rather than queried per card — seven cards would
 * otherwise mean seven requests for data one call already returns.
 */
function EvalTrend({ reports }: { reports: EvalReport[] }) {
  if (reports.length === 0) return null;
  // Newest last, so the row reads left-to-right like a timeline.
  const recent = reports.slice(0, 3).reverse();
  return (
    <span className="inline-flex items-center gap-050" aria-label="Recent eval runs">
      {recent.map((r) => (
        <span
          key={r.id}
          title={`${r.suiteName ?? r.suiteId} — ${r.status}${
            r.createdAt ? ` · ${new Date(r.createdAt).toLocaleDateString()}` : ""
          }`}
          className={cn(
            "h-2 w-2 rounded-full",
            r.status === "pass"
              ? "bg-background-success-bold"
              : r.status === "fail"
                ? "bg-background-danger-bold"
                : "bg-border",
          )}
        />
      ))}
    </span>
  );
}

/** Past tense, because the log records what happened rather than what to do. */
const CHANGE_VERBS: Record<string, string> = {
  "agent.publish": "published",
  "agent.rollback": "rolled back",
  "agent.archive": "archived",
  "agent.restore": "restored",
};

function changeVerb(action: string): string {
  return CHANGE_VERBS[action] ?? action.replace(/^agent\./, "").replace(/_/g, " ");
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
function RecentChanges() {
  // Tenant-wide, so no botId. Note chain.checked is tenant-scoped whether or
  // not entries are filtered — see the note on fetchChangeLog.
  const { data, isLoading, isError, error } = useChangeLog(undefined, 10);
  const entries = data?.entries ?? [];
  const chain = data?.chain;

  // An audit log that removes itself when its request fails is worse than one
  // that is down: the screen looks the same as a tenant that has never
  // published, so nobody goes looking. `isError` used to return null with
  // `isLoading`, which is exactly the fallback that hides a 500.
  if (isError) {
    return (
      <section className="mt-300 rounded-large border border-border-danger bg-surface p-250">
        <h2 className="text-body font-semibold">Recent changes</h2>
        <p className="mt-150 text-body-small text-text-danger">
          The change log could not be read, so this is not a record of nothing happening — it is a
          record that could not be shown.{" "}
          {error instanceof Error ? error.message : "Request failed"}
        </p>
      </section>
    );
  }
  if (isLoading) return null;

  return (
    <section className="mt-300 rounded-large border border-border bg-surface p-250">
      <div className="flex flex-wrap items-center gap-100">
        <h2 className="text-body font-semibold">Recent changes</h2>
        {chain && !chain.ok ? (
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
        ) : null}
      </div>

      {entries.length === 0 ? (
        <p className="mt-150 text-body-small text-text-subtle">
          Nothing published, rolled back, archived or restored yet.
        </p>
      ) : (
        <ul className="mt-150 divide-y divide-border">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-wrap items-baseline gap-100 py-100">
              <span className="text-body-small font-medium">{entry.actorUserId ?? "unknown"}</span>
              <span className="text-body-small text-text-subtle">{changeVerb(entry.action)}</span>
              <span className="font-mono text-body-tiny text-text-subtle">{entry.botId}</span>
              {entry.versionLabel ? <Lozenge tone="neutral">{entry.versionLabel}</Lozenge> : null}
              {entry.changed?.length ? (
                <span
                  className="text-body-tiny text-text-subtlest"
                  title="Components that differ from the version before it"
                >
                  {entry.changed.join(", ")}
                </span>
              ) : null}
              <span className="ml-auto text-body-tiny text-text-subtlest">
                {entry.at
                  ? new Date(entry.at).toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "—"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function canArchive(card: AgentCardSummary): boolean {
  if (card.archivedAt) return true;
  // Mirrors db.archive_agent_studio_card so the button never offers a 409.
  // `isFirstParty` comes from the server: inferring it from cardSource was
  // wrong, because a first-party card with a published row reports "published",
  // so its button enabled and then failed.
  //
  // A live deployment is no longer a blocker. It used to be, on both sides, and
  // that made the button dead for every card that had ever shipped — archiving
  // now retires the deployment, which is what taking a card out of service means.
  return !card.isFirstParty && card.botId !== card.entryBotId;
}

function archiveReason(card: AgentCardSummary): string | undefined {
  if (card.archivedAt) return "Bring this card back onto the roster";
  if (card.isFirstParty) return "First-party cards are re-seeded on API boot";
  if (card.botId === card.entryBotId) return "This card takes inbound traffic";
  if (card.deploymentStatus === "live")
    return "Retires the live deployment and takes the card off the roster";
  return undefined;
}

function FleetIndex() {
  const navigate = Route.useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const { data, isLoading, isError, error } = useAgentStudioCards(showArchived);
  const templates = useAgentStudioTemplates();
  // One request for the whole fleet's eval history; grouped per card below.
  // Reports with a null botId are tenant-wide suite runs, not this card's.
  const evalReports = useEvalReports();
  const reportsByBot = new Map<string, EvalReport[]>();
  for (const report of evalReports.data ?? []) {
    if (!report.botId) continue;
    const bucket = reportsByBot.get(report.botId);
    if (bucket) bucket.push(report);
    else reportsByBot.set(report.botId, [report]);
  }
  const clone = useCloneAgentCard();
  const archive = useArchiveAgentCard();

  // Archiving a live card retires its deployment, so it asks first — but not
  // with `window.confirm`. The Prompt Studio's own preset dialog carries the
  // note explaining why: browser chrome titled "localhost:8080 says", blocking
  // the renderer, unthemed and unstyleable. The app already ships the
  // replacement it names, and this screen was the last caller.
  const [archivePending, setArchivePending] = useState<AgentCardSummary | null>(null);

  const runArchive = async (card: AgentCardSummary, next: boolean) => {
    try {
      await archive.mutateAsync({ botId: card.botId, archived: next });
      toast.success(next ? `Archived ${card.name}` : `Restored ${card.name}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed");
    }
  };

  const onArchive = async (card: AgentCardSummary) => {
    if (!card.archivedAt) {
      setArchivePending(card);
      return;
    }
    await runArchive(card, false);
  };
  const [open, setOpen] = useState(false);
  // Empty until the catalog loads. Seeding "lapse" up front meant the <select>
  // rendered its first real option while state still said "lapse", so Create
  // cloned a template the user never picked — or 409'd on an unknown id.
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    const rows = templates.data ?? [];
    if (!rows.length) return;
    if (rows.some((t) => t.id === templateId)) return;
    setTemplateId(rows[0].id);
    setName(rows[0].label);
  }, [templates.data, templateId]);

  return (
    <AppShell>
      <div className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-border px-400 py-200">
          <div>
            <h1 className="heading-medium font-semibold">Agent studio</h1>
            <p className="text-body-small text-text-subtle">
              First-party mouths plus tenant clones. Publish is a compiler — clone a card, attach
              connectors, canary, then ship.
            </p>
          </div>
          <div className="flex items-center gap-100">
            <label className="mr-100 flex items-center gap-050 text-body-small text-text-subtle">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
              />
              Show archived
            </label>
            <Button
              type="button"
              variant="outline"
              onClick={() => void navigate({ to: "/agent-studio/skills" })}
            >
              Skills library
            </Button>
            <Button type="button" onClick={() => setOpen(true)}>
              Clone card
            </Button>
          </div>
        </header>
        {open ? (
          <div className="border-b border-border bg-surface-sunken px-400 py-200">
            <div className="text-body font-semibold">Clone a template</div>
            <p className="mb-150 text-body-small text-text-subtle">
              Lapse / Hardship / Clerk are recipes, not a fifth first-party mouth. Clone the skill
              first if the card pins one.
            </p>
            <div className="flex flex-wrap items-end gap-100">
              <label className="text-body-small">
                Template
                <select
                  className="ml-075 rounded-medium border border-border bg-surface px-100 py-050"
                  value={templateId}
                  onChange={(e) => {
                    setTemplateId(e.target.value);
                    const t = (templates.data ?? []).find((x) => x.id === e.target.value);
                    if (t) setName(t.label);
                  }}
                >
                  {(templates.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-body-small">
                Name
                <Input className="ml-075" value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <Button
                disabled={clone.isPending || !templateId}
                onClick={() => {
                  void clone
                    .mutateAsync({ templateId, name })
                    .then((row) => {
                      toast.success(`Draft ${row.name} created — compile before publish`);
                      setOpen(false);
                      void navigate({ to: "/agent-studio/$botId", params: { botId: row.botId } });
                    })
                    .catch((err: Error) => toast.error(err.message));
                }}
              >
                Create draft
              </Button>
              <Button variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}
        {isLoading && !data ? (
          <div className="grid flex-1 place-items-center">
            <LoadingState label="Loading fleet" />
          </div>
        ) : isError ? (
          <div className="p-400 text-text-danger">
            {error instanceof Error ? error.message : "Failed to load cards"}
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 content-start gap-200 overflow-y-auto p-400 md:grid-cols-2">
            {/* Scrolls, and starts at the top.
                The grid is a flex child of `h-full flex-col` inside the
                AppShell's `overflow-hidden` main region, so with no scroll
                container of its own the list was simply cut off: seven cards
                came to 1899px inside a 574px box and the last three — the
                tenant clones — could not be reached at any window size, with
                no scrollbar to suggest they existed. `min-h-0` is what lets a
                flex child shrink below its content; `content-start` keeps the
                rows at natural height when there are only a few cards. */}

            {(data ?? []).map((card) => (
              // A div, not a button: Archive and Sandbox live inside it.
              <div
                key={card.botId}
                className={cn(
                  "rounded-large border bg-surface p-250 text-left focus-within:border-border-brand hover:border-border-brand",
                  card.archivedAt ? "border-dashed border-border opacity-70" : "border-border",
                )}
              >
                <div className="flex items-start justify-between gap-200">
                  <div className="flex items-center gap-150">
                    <span className="grid h-8 w-8 place-items-center rounded-full bg-background-brand-subtlest text-text-brand">
                      <Bot className="h-4 w-4" />
                    </span>
                    <div>
                      <button
                        type="button"
                        className="text-body font-semibold hover:text-text-brand"
                        onClick={() =>
                          void navigate({
                            to: "/agent-studio/$botId",
                            params: { botId: card.botId },
                          })
                        }
                      >
                        {card.name}
                      </button>
                      <div className="font-mono text-body-tiny text-text-subtle">{card.botId}</div>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-050">
                    <Lozenge tone={routing(card).tone}>{routing(card).label}</Lozenge>
                    <Lozenge
                      tone={
                        card.deploymentStatus === "live"
                          ? "success"
                          : card.deploymentStatus === "empty"
                            ? "danger"
                            : "neutral"
                      }
                    >
                      {card.deploymentStatus === "live"
                        ? `deployed · ${card.trafficPct ?? 100}%`
                        : card.deploymentStatus === "published"
                          ? "published, not deployed"
                          : card.deploymentStatus === "draft"
                            ? "draft only"
                            : "no version"}
                    </Lozenge>
                  </div>
                </div>
                <p className="mt-150 text-body-small text-text-subtle">{card.purpose}</p>
                <div className="mt-100 text-body-tiny text-text-subtlest">
                  {routing(card).help(card.entryBotId)}
                </div>
                <div className="mt-150 flex flex-wrap gap-100">
                  {card.channels.map((ch) => (
                    <Lozenge key={ch} tone="neutral">
                      {ch}
                    </Lozenge>
                  ))}
                  <Lozenge tone="neutral">{card.toolCount} tools</Lozenge>
                  <Lozenge tone="neutral">{card.skills.length} skills</Lozenge>
                  <EvalTrend reports={reportsByBot.get(card.botId) ?? []} />
                  {card.deploymentStatus === "live" && card.evalStatus === "skipped" ? (
                    <Lozenge
                      tone="warning"
                      title="Carrying production traffic with no eval suite on record. The publish gate allows this; nothing has verified the card behaves."
                    >
                      live without evals
                    </Lozenge>
                  ) : (
                    <Lozenge
                      tone={card.evalStatus === "pass" ? "success" : "neutral"}
                      title="Eval suite result. 'skipped' means the suite has not run — not a failure."
                    >
                      evals: {card.evalStatus}
                    </Lozenge>
                  )}
                  {card.hasDraft ? (
                    <button
                      type="button"
                      title="Open the editor on this card — it resumes the newest draft"
                      onClick={() =>
                        void navigate({
                          to: "/agent-studio/$botId",
                          params: { botId: card.botId },
                        })
                      }
                      className="rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-border-brand"
                    >
                      <Lozenge tone="warning">unpublished draft →</Lozenge>
                    </button>
                  ) : null}
                </div>
                <div className="mt-150 flex flex-wrap items-center justify-between gap-100">
                  <span className="text-body-tiny text-text-subtlest">
                    {card.lastPublish
                      ? `Last published ${new Date(card.lastPublish).toLocaleDateString(undefined, {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                        })}`
                      : "Never published"}
                  </span>
                  <div className="flex gap-100">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() =>
                        void navigate({ to: "/agent-studio/$botId", params: { botId: card.botId } })
                      }
                    >
                      Edit
                    </Button>
                    {card.reachability !== "archived" ? (
                      <Button
                        type="button"
                        variant="outline"
                        // A card with no prompt version has nothing to rehearse:
                        // the sandbox would open and fall back to its default
                        // bot, which is a different card than the one clicked.
                        disabled={card.deploymentStatus === "empty"}
                        title={
                          card.deploymentStatus === "empty"
                            ? "No version to run — author and save a draft first"
                            : undefined
                        }
                        onClick={() =>
                          void navigate({ to: "/sandbox", search: { botId: card.botId } })
                        }
                      >
                        Sandbox
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      disabled={archive.isPending || !canArchive(card)}
                      title={archiveReason(card)}
                      onClick={() => void onArchive(card)}
                    >
                      {card.archivedAt ? "Restore" : "Archive"}
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <RecentChanges />
      </div>
      <AlertDialog
        open={archivePending !== null}
        onOpenChange={(next) => {
          if (!next) setArchivePending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Archive {archivePending?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              {archivePending?.deploymentStatus === "live"
                ? "Its live deployment is retired — the card stops taking traffic immediately. History is kept, and restoring it needs a fresh publish."
                : "It keeps its history and can be restored."}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it live</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const card = archivePending;
                setArchivePending(null);
                if (card) void runArchive(card, true);
              }}
            >
              Archive
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}
