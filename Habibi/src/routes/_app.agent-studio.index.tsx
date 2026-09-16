import { Fragment, useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import {
  useAgentStudioCards,
  useEvalReports,
  useRunEvalSchedule,
  useAgentStudioTemplates,
  useArchiveAgentCard,
  useCloneAgentCard,
  entryBindingLabel,
  type AgentCardSummary,
  type EvalReport,
} from "@/api/agent-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { Lozenge } from "@/components/ui/lozenge";
import { gateTone } from "@/lib/gate-status";
import { Button } from "@/components/ui/button";
import { ReasonedAction } from "@/components/ui/reasoned-action";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { SelectField } from "@/components/ui/select";
import { archiveAvailability, groupRoster, sandboxAvailability } from "@/lib/agent-roster";
import { cn } from "@/lib/utils";
import { ROUTING } from "@/lib/agent-roster";
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
import { EvalTrend } from "@/components/fleet/EvalTrend";
import { RecentChanges } from "@/components/fleet/RecentChanges";

export const Route = createFileRoute("/_app/agent-studio/")({
  component: FleetIndex,
});

/** Tolerates a reachability value this build does not know about. */
function routing(card: AgentCardSummary) {
  return ROUTING[card.reachability] ?? ROUTING.unreachable;
}

function FleetIndex() {
  const navigate = Route.useNavigate();
  const [showArchived, setShowArchived] = useState(false);
  const { data, isLoading, isError, error, refetch, isFetching } =
    useAgentStudioCards(showArchived);
  const templates = useAgentStudioTemplates();
  // One request for the whole fleet's eval history; grouped per card below.
  // Reports with a null botId are tenant-wide suite runs, not this card's.
  const evalReports = useEvalReports(undefined, undefined, { perBot: 3 });
  const schedule = useRunEvalSchedule();
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
  // Empty until the catalog loads. Seeding "lapse" up front meant the picker
  // rendered its first real option while state still said "lapse", so Create
  // cloned a template the user never picked — or 409'd on an unknown id.
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");

  useEffect(() => {
    const rows = templates.data ?? [];
    const first = rows[0];
    if (!first) return;
    if (rows.some((t) => t.id === templateId)) return;
    setTemplateId(first.id);
    setName(first.label);
  }, [templates.data, templateId]);

  return (
    <>
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
            <label className="mr-100 flex items-center gap-075 text-body-small text-text-subtle">
              <Checkbox
                checked={showArchived}
                onCheckedChange={(v) => setShowArchived(v === true)}
              />
              Show archived
            </label>
            <Button
              type="button"
              variant="outline"
              disabled={schedule.isPending}
              onClick={() => void schedule.mutateAsync()}
            >
              {schedule.isPending ? "Running…" : "Run continuous suite"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void navigate({ to: "/agent-studio/skills" })}
            >
              Skills library
            </Button>
            <Button type="button" onClick={() => setOpen(true)}>
              New agent from template
            </Button>
          </div>
        </header>
        {open ? (
          <div className="border-b border-border bg-surface-sunken px-400 py-200">
            <div className="text-body font-semibold">New agent from a template</div>
            <p className="mb-150 text-body-small text-text-subtle">
              Lapse / Hardship / Clerk are recipes, not a fifth first-party mouth. The card comes
              from the template; the prompt and flow are copied from the source agent — its own card
              edits are not. Clone the skill first if the card pins one.
            </p>
            {templates.isPending ? (
              <LoadingState label="Loading templates" />
            ) : templates.isError ? (
              <div className="flex flex-wrap items-center gap-100">
                <QueryErrorBanner label="the template catalog" error={templates.error} />
                <Button variant="outline" onClick={() => void templates.refetch()}>
                  Retry
                </Button>
              </div>
            ) : (
              <form
                className="flex flex-wrap items-end gap-100"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (clone.isPending || !templateId) return;
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
                <div className="flex items-center gap-075 text-body-small">
                  Template
                  <SelectField
                    aria-label="Template"
                    className="ml-075 w-[12.5rem]"
                    value={templateId}
                    onChange={(v) => {
                      setTemplateId(v);
                      const t = (templates.data ?? []).find((x) => x.id === v);
                      if (t) setName(t.label);
                    }}
                    options={(templates.data ?? []).map((t) => ({ value: t.id, label: t.label }))}
                  />
                </div>
                <label className="text-body-small">
                  Name
                  <Input
                    className="ml-075"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                {/* A form, so Enter in the name field submits instead of doing nothing. */}
                <Button type="submit" disabled={clone.isPending || !templateId}>
                  {clone.isPending ? "Creating…" : "Create draft"}
                </Button>
                <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                  Cancel
                </Button>
              </form>
            )}
          </div>
        ) : null}
        {isLoading && !data ? (
          <div className="grid flex-1 place-items-center">
            <LoadingState label="Loading fleet" />
          </div>
        ) : isError ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-100 p-400">
            <p className="text-body text-text-subtle">Couldn’t load the fleet.</p>
            <p className="text-body-small text-text-danger">
              {error instanceof Error ? error.message : "Failed to load cards"}
            </p>
            <Button
              type="button"
              variant="outline"
              loading={isFetching}
              disabled={isFetching}
              onClick={() => void refetch()}
            >
              Retry
            </Button>
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

            {groupRoster(data ?? []).map((group) => (
              <Fragment key={group.key}>
                {/* Headings are grid children spanning the row, not wrappers:
                    one grid and one scroll container, so the columns still line
                    up across a group boundary. */}
                <h2 className="col-span-full mt-100 flex items-baseline gap-100 text-body-small font-semibold text-text-subtle first:mt-0">
                  {group.label}
                  <span className="font-normal text-text-subtlest">{group.cards.length}</span>
                </h2>
                {group.cards.map((card) => (
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
                          <div className="font-mono text-body-tiny text-text-subtle">
                            {card.botId}
                          </div>
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-050">
                        {card.entryBindings.length > 0 ? (
                          card.entryBindings.map((b) => (
                            <Lozenge key={b.id} tone="success" title={b.note || undefined}>
                              {entryBindingLabel(b)}
                            </Lozenge>
                          ))
                        ) : (
                          <Lozenge tone={routing(card).tone}>{routing(card).label}</Lozenge>
                        )}
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
                      <EvalTrend
                        reports={reportsByBot.get(card.botId) ?? []}
                        failed={evalReports.isError}
                      />
                      {card.deploymentStatus === "live" && card.evalStatus === "skipped" ? (
                        <Lozenge
                          tone="warning"
                          title="Carrying production traffic with no eval suite on record. The publish gate allows this; nothing has verified the card behaves."
                        >
                          live without evals
                        </Lozenge>
                      ) : (
                        <Lozenge
                          tone={gateTone(card.evalStatus)}
                          title={
                            card.evalStatus === "stale"
                              ? "Suites passed against a previous save of this card. Re-run regression and redteam on the current draft."
                              : "Eval suite result. 'skipped' means the suite has not run — not a failure."
                          }
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
                          ? `Last published ${new Date(card.lastPublish).toLocaleDateString(
                              undefined,
                              {
                                year: "numeric",
                                month: "short",
                                day: "numeric",
                              },
                            )}`
                          : "Never published"}
                      </span>
                      <div className="flex gap-100">
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() =>
                            void navigate({
                              to: "/agent-studio/$botId",
                              params: { botId: card.botId },
                            })
                          }
                        >
                          Edit
                        </Button>
                        {card.reachability !== "archived" ? (
                          <ReasonedAction
                            availability={sandboxAvailability(card)}
                            onClick={() =>
                              void navigate({ to: "/sandbox", search: { botId: card.botId } })
                            }
                          >
                            Sandbox
                          </ReasonedAction>
                        ) : null}
                        <ReasonedAction
                          availability={archiveAvailability(card)}
                          // Per card, not per page. `archive.isPending` on its own
                          // is one mutation shared by every card, so archiving one
                          // greyed out the Archive button on all the others.
                          busy={archive.isPending && archive.variables?.botId === card.botId}
                          onClick={() => void onArchive(card)}
                        >
                          {card.archivedAt ? "Restore" : "Archive"}
                        </ReasonedAction>
                      </div>
                    </div>
                  </div>
                ))}
              </Fragment>
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
    </>
  );
}
