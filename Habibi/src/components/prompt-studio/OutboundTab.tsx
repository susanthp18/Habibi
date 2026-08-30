// The Outbound tab — being the one who dialled, authored on the card.
//
// It sits between Policy and Evals for a reason: after the constraints that
// bound it, before the gate that proves it.
//
// Four panes, matching the four questions an outbound agent has to answer that
// an inbound one never does — why are we calling, when do we try again, what
// number do we call from, and what happens after we hang up.

import { useState } from "react";
import { ArrowRightLeft, Clock, PhoneOutgoing, ShieldAlert, Target } from "lucide-react";

import {
  useCadenceCases,
  useCampaigns,
  useCreateCampaign,
  useMissions,
  useNonpaymentReasons,
  useObligations,
  useOutboundVocabulary,
  usePreviewCohort,
  useReachStats,
  useSetCampaignStatus,
  REASON_LABEL,
  type CampaignSelector,
} from "@/api/outbound";
import { isAuthoredCard, type AgentCard } from "@/api/agent-card";
import { useCompilePreview } from "@/api/agent-studio";
import {
  CadencesEditor,
  DirectionPanel,
  MissionsEditor,
  PostCallEditor,
  resolvedOutbound,
} from "./OutboundCardEditor";
import { NumberPoolTable } from "./NumberPoolTable";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { cn } from "@/lib/utils";

type Pane = "missions" | "cadence" | "reach" | "aftercall";

const PANES: Array<{ key: Pane; label: string; icon: typeof Target }> = [
  { key: "missions", label: "Missions", icon: Target },
  { key: "cadence", label: "Cadence", icon: Clock },
  { key: "reach", label: "Reach", icon: PhoneOutgoing },
  { key: "aftercall", label: "After the call", icon: ArrowRightLeft },
];

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: LozengeTone;
}) {
  return (
    <div className="rounded-medium border border-border bg-surface px-150 py-100">
      <div className="text-body-tiny uppercase tracking-wide text-text-subtlest">{label}</div>
      <div
        className={cn("mt-050 heading-small tabular-nums", tone === "danger" && "text-text-danger")}
      >
        {value}
      </div>
      {hint ? <div className="mt-025 text-body-tiny text-text-subtle">{hint}</div> : null}
    </div>
  );
}

function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-medium border border-dashed border-border bg-surface-sunken/40 px-200 py-250 text-center">
      <div className="text-body font-medium text-text">{title}</div>
      <p className="mx-auto mt-050 max-w-prose text-body-small text-text-subtle">{body}</p>
    </div>
  );
}

/**
 * G-OB1..8 for the card as it stands in the editor, not as last published.
 *
 * The gates are the only honest answer to "can I ship this", and they are cheap
 * — the compile endpoint accepts an unsaved card. Showing them beside the
 * controls that cause them means a cadence over the borrower cap or a mission
 * the graph does not claim is visible where it was typed, rather than at the
 * publish button under a gate number.
 */
function OutboundGates({ botId, card, flow }: { botId: string; card: AgentCard; flow?: unknown }) {
  const authored = isAuthoredCard(card);
  const preview = useCompilePreview(botId, { agentCard: card, flow }, authored);
  if (!authored) return null;
  if (preview.isError) return <Lozenge tone="neutral">compiler unreachable</Lozenge>;
  const gates = (preview.data?.gates ?? []).filter((g) => g.gate.startsWith("G-OB"));
  if (gates.length === 0) return <Lozenge tone="neutral">checking…</Lozenge>;
  const failing = gates.filter((g) => g.status === "fail");
  const skipped = gates.every((g) => g.status === "skipped");
  if (skipped) return <Lozenge tone="neutral">outbound gates skipped — inbound only</Lozenge>;
  if (failing.length === 0) {
    return <Lozenge tone="success">{gates.length} outbound gates pass</Lozenge>;
  }
  return (
    <div className="w-full space-y-050 rounded-medium border border-border-danger bg-background-danger-subtler px-150 py-100">
      <div className="flex items-center gap-100 text-body-small font-medium text-text-danger-bolder">
        <ShieldAlert aria-hidden className="size-100 shrink-0" />
        {failing.length === 1
          ? "1 outbound gate blocks publish"
          : `${failing.length} outbound gates block publish`}
      </div>
      <ul className="space-y-025">
        {failing.map((g) => (
          <li key={g.gate} className="text-body-small text-text-danger-bolder">
            <span className="font-mono">{g.gate}</span> {g.name}
            {g.detail ? <span className="ml-075 text-text-subtle">{g.detail}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Build the cohort, count it, then create the run - in that order.
 *
 *  The order is the design. A campaign is the one object in this product whose
 *  accidental creation rings real phones, so the count comes before the run
 *  exists and the run is created paused. Nothing on this panel dials.
 *
 *  `campaign_runs.selector` has been a stored, validated jsonb column since the
 *  table was created and nothing ever read it; a cohort could only be built by
 *  POSTing a list of customer ids. This is the screen that column was for.
 */
function CohortBuilder({ objectives }: { objectives: string[] }) {
  const [name, setName] = useState("");
  const [objective, setObjective] = useState(objectives[0] ?? "");
  const [dpdMin, setDpdMin] = useState("1");
  const [dpdMax, setDpdMax] = useState("");
  const [minOutstanding, setMinOutstanding] = useState("");
  const [excludeOpenPromise, setExcludeOpenPromise] = useState(true);
  const [excludeOnHold, setExcludeOnHold] = useState(true);
  const [quietDays, setQuietDays] = useState("3");
  const [limit, setLimit] = useState("500");

  const preview = usePreviewCohort();
  const create = useCreateCampaign();

  /**
   * Parse one cohort field, rejecting values the selector cannot mean.
   *
   * Every field here is a count, a day offset or an amount, and none of them
   * has a negative reading — but this used to pass `Number(raw)` straight
   * through, so "-5" became a days-since-contact window of minus five and a
   * `dpdMin` that matches accounts which are not overdue. The preview is
   * server-side and would have counted whatever that means, which is exactly
   * what makes it hard to notice: you get a number back, so it looks like it
   * worked.
   */
  const num = (raw: string): number | undefined => {
    const parsed = Number(raw);
    if (raw.trim() === "" || Number.isNaN(parsed) || parsed < 0) return undefined;
    return parsed;
  };

  const selector = (): CampaignSelector => ({
    dpdMin: num(dpdMin),
    dpdMax: num(dpdMax),
    minOutstandingInr: num(minOutstanding),
    excludeOpenPromise,
    excludeOnHold,
    excludeContactedWithinDays: num(quietDays),
    // `??`, not `||`, is right here — but 0 is not a limit anyone means, it is
    // "call nobody", and `num` treating it as a real value made `?? 500` skip
    // the default for a run that would then match zero customers and read as an
    // empty cohort rather than as a typo.
    limit: num(limit) || 500,
  });

  /** Fields the operator typed that `num` discarded, so the panel can say so. */
  const rejected = [
    ["Min DPD", dpdMin],
    ["Max DPD", dpdMax],
    ["Min outstanding", minOutstanding],
    ["Quiet days", quietDays],
    ["Limit", limit],
  ].filter(([, raw]) => raw.trim() !== "" && num(raw) === undefined);

  // Deliberately gated on a preview. Creating a run without having looked at
  // who is in it is the mistake this whole panel exists to make difficult.
  const counted = preview.data?.matched ?? null;
  const canCreate = name.trim().length > 0 && objective.length > 0 && (counted ?? 0) > 0;
  const names = (preview.data?.sample ?? []).slice(0, 3).map((m) => m.name ?? m.customer_id);

  return (
    <div className="rounded-medium border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <span className="text-body-small font-semibold">New run</span>
        <span className="text-body-tiny text-text-subtlest">
          count the cohort first &mdash; the run is created paused
        </span>
      </div>

      {rejected.length > 0 ? (
        <div className="border-b border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
          Ignored (not a non-negative number): {rejected.map(([label]) => label).join(", ")}. Those
          filters are not being applied.
        </div>
      ) : null}
      <div className="grid gap-100 px-150 py-100 sm:grid-cols-2">
        <div className="space-y-050">
          <Label htmlFor="cohort-name">Run name</Label>
          <Input
            id="cohort-name"
            value={name}
            placeholder="August bounce cure"
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-050">
          <Label htmlFor="cohort-objective">Mission</Label>
          <select
            id="cohort-objective"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            className="h-200 w-full rounded-small border border-border bg-surface px-100 text-body-small"
          >
            {objectives.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid gap-100 px-150 pb-100 sm:grid-cols-4">
        <div className="space-y-050">
          <Label htmlFor="cohort-dpd-min">DPD from</Label>
          <Input
            id="cohort-dpd-min"
            inputMode="numeric"
            value={dpdMin}
            onChange={(e) => setDpdMin(e.target.value)}
          />
        </div>
        <div className="space-y-050">
          <Label htmlFor="cohort-dpd-max">DPD to</Label>
          <Input
            id="cohort-dpd-max"
            inputMode="numeric"
            value={dpdMax}
            placeholder="any"
            onChange={(e) => setDpdMax(e.target.value)}
          />
        </div>
        <div className="space-y-050">
          <Label htmlFor="cohort-outstanding">Outstanding over</Label>
          <Input
            id="cohort-outstanding"
            inputMode="numeric"
            value={minOutstanding}
            placeholder="any"
            onChange={(e) => setMinOutstanding(e.target.value)}
          />
        </div>
        <div className="space-y-050">
          <Label htmlFor="cohort-limit">At most</Label>
          <Input
            id="cohort-limit"
            inputMode="numeric"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-150 px-150 pb-100">
        <label className="flex items-center gap-075 text-body-small">
          <Checkbox
            checked={excludeOpenPromise}
            onCheckedChange={(v) => setExcludeOpenPromise(v === true)}
          />
          Skip anyone with a promise still to fall due
        </label>
        <label className="flex items-center gap-075 text-body-small">
          <Checkbox checked={excludeOnHold} onCheckedChange={(v) => setExcludeOnHold(v === true)} />
          Skip anyone on hold
        </label>
        <label className="flex items-center gap-075 text-body-small">
          Quiet for
          <Input
            aria-label="Days since last contact"
            inputMode="numeric"
            value={quietDays}
            onChange={(e) => setQuietDays(e.target.value)}
            className="w-300"
          />
          days
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-100 border-t border-border px-150 py-100">
        <Button
          size="sm"
          variant="secondary"
          disabled={preview.isPending}
          onClick={() => preview.mutate(selector())}
        >
          {preview.isPending ? "Counting..." : "Count cohort"}
        </Button>
        {preview.isError ? (
          <span className="text-body-small text-text-danger">
            {(preview.error as Error).message}
          </span>
        ) : counted !== null ? (
          <span className="text-body-small text-text-subtle">
            <strong className="tabular-nums text-text">{counted}</strong> borrowers
            {preview.data?.capped ? " (capped by the limit above)" : ""}
            {names.length > 0 ? " \u00b7 e.g. " + names.join(", ") : ""}
          </span>
        ) : (
          <span className="text-body-small text-text-subtlest">
            Nothing is created and nothing dials until you count.
          </span>
        )}
        <span className="ml-auto">
          <Button
            size="sm"
            disabled={!canCreate || create.isPending}
            onClick={() =>
              create.mutate(
                { name: name.trim(), objective, selector: selector(), botId },
                {
                  onSuccess: () => {
                    setName("");
                    preview.reset();
                  },
                },
              )
            }
          >
            {create.isPending ? "Creating..." : "Create paused run"}
          </Button>
        </span>
      </div>
      {create.isError ? (
        <p className="px-150 pb-100 text-body-small text-text-danger">
          {(create.error as Error).message}
        </p>
      ) : null}
    </div>
  );
}

/**
 * @param botId The card being edited. Was not a prop at all, so every sentence
 * on this tab that says "this card" described the default bot instead.
 * @param card The draft being edited. `card.outbound` had no editor anywhere:
 * nine members, three nested models and eight compile gates reachable only by
 * writing JSON into the database by hand.
 */
export function OutboundTab({
  botId,
  card,
  flow,
  onChange,
}: {
  botId: string;
  card: AgentCard;
  flow?: unknown;
  onChange?: (next: AgentCard) => void;
}) {
  const [pane, setPane] = useState<Pane>("missions");
  const missions = useMissions(botId);
  const vocabQuery = useOutboundVocabulary();
  const stats = useReachStats(14);
  const campaigns = useCampaigns();
  const cadence = useCadenceCases();
  const reasons = useNonpaymentReasons(30);
  const obligations = useObligations();
  const setStatus = useSetCampaignStatus();

  const config = missions.data;
  const vocab = vocabQuery.data;
  // The draft, not the deployment. Every other card tab edits what will be
  // published; this one used to render what already was, which is why it could
  // only ever describe the outbound block and never change it.
  const draft = resolvedOutbound(card);
  const dials = draft.direction !== "inbound";
  const editable = Boolean(onChange) && isAuthoredCard(card);
  const handoffTargets = (card.handoffs ?? [])
    .map((h) => h.to_bot_id)
    .filter((t): t is string => Boolean(t));
  // Deliberately the *published* card's missions, not the draft's. A campaign
  // run is created against what is live: offering an objective that exists only
  // in an unsaved edit would be offering a button the create endpoint refuses.
  const objectiveKeys = (config?.objectives ?? []).map((o) => o.key);

  return (
    <div className="space-y-150">
      {/* Two registers on one tab, and saying which is which is the difference
          between a screen you can act on and one you can only half trust.
          Missions is this card's own configuration; the other three panes are
          the tenant's live outbound — every bot's attempts, ladders, runs and
          obligations, not this one's. The old copy said "everything here is
          published with the card", which was true of one pane in four. */}
      <p className="max-w-prose text-body-small text-text-subtle">
        An outbound agent is not the inbound script with a different greeting — we chose the
        borrower, the moment and the reason. Missions, retry ladders and the after-call rules are
        authored here and published with this card, so the sentence the agent said and the schedule
        that produced the call carry one version number. The live figures below them — reach, open
        ladders, campaign runs, outstanding promises — are the whole tenant&apos;s dialling, not
        this card&apos;s alone.
      </p>

      <div className="flex flex-wrap items-center gap-050">
        {PANES.map((p) => {
          const Icon = p.icon;
          const active = pane === p.key;
          return (
            <button
              key={p.key}
              type="button"
              onClick={() => setPane(p.key)}
              className={cn(
                "inline-flex items-center gap-075 rounded-small px-100 py-075 text-body-small transition-colors",
                active
                  ? "bg-surface font-semibold text-text shadow-sm"
                  : "text-text-subtle hover:bg-surface-sunken hover:text-text",
              )}
            >
              <Icon className="size-100" aria-hidden />
              {p.label}
            </button>
          );
        })}
        <span className="ml-auto">
          <Lozenge tone={dials ? "success" : "neutral"}>
            {dials ? `direction: ${draft.direction}` : "inbound only — this agent never dials"}
          </Lozenge>
        </span>
      </div>

      {!editable && onChange ? (
        <div className="rounded-medium border border-dashed border-border p-200 text-body-small text-text-subtle">
          This version has no Agent Card, so the outbound block cannot be edited here. Clone a card
          from the fleet index, or publish once to stamp the first-party defaults onto this bot.
        </div>
      ) : null}

      {pane === "missions" && (
        <div className="space-y-150">
          <OutboundGates botId={botId} card={card} flow={flow} />
          {vocabQuery.isLoading ? (
            <LoadingState label="Loading the outbound vocabulary" />
          ) : !vocab ? (
            <Empty
              title="Vocabulary unavailable"
              body="The objectives, outcome codes and authority profiles this editor offers come from the API so they cannot drift from what the compiler accepts. Nothing is offered rather than guessed — check the API and reload."
            />
          ) : (
            <>
              <DirectionPanel
                card={card}
                onChange={onChange ?? (() => {})}
                vocab={vocab}
                editable={editable}
              />
              <MissionsEditor
                card={card}
                onChange={onChange ?? (() => {})}
                vocab={vocab}
                graphEntries={config?.graphEntries ?? {}}
                editable={editable}
              />
            </>
          )}
        </div>
      )}

      {pane === "cadence" && (
        <div className="space-y-150">
          {vocab ? (
            <CadencesEditor
              card={card}
              onChange={onChange ?? (() => {})}
              vocab={vocab}
              editable={editable}
              handoffTargets={handoffTargets}
            />
          ) : null}
          <p className="max-w-prose text-body-small text-text-subtle">
            Cadence retries the <em>same</em> mission. Only the treatment engine may change the
            action — a dialler with its own escalation ladder would have no expected value, no
            propensity and no audit trail.
          </p>
          {cadence.isLoading ? (
            <LoadingState label="Loading retry ladders" />
          ) : (cadence.data ?? []).length === 0 ? (
            <Empty
              title="No open ladders"
              body="A ladder opens when a call ends without resolving the case and the outcome is one worth trying again. A refusal never is: the borrower answered and said no."
            />
          ) : (
            <ul className="divide-y divide-border rounded-medium border border-border bg-surface">
              {(cadence.data ?? []).map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-100 px-150 py-100">
                  <span className="text-body-small font-medium">
                    {c.customer_name ?? c.customer_id}
                  </span>
                  <span className="font-mono text-body-tiny text-text-subtle">{c.objective}</span>
                  <Lozenge tone={c.state === "open" ? "information" : "neutral"}>
                    {c.state === "open"
                      ? `attempt ${c.attempts}/${c.max_attempts}`
                      : c.stopped_reason || c.state}
                  </Lozenge>
                  <span className="ml-auto text-body-tiny text-text-subtlest">
                    {c.next_attempt_at
                      ? `next ${new Date(c.next_attempt_at).toLocaleString()}`
                      : c.last_outcome || "—"}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {objectiveKeys.length > 0 ? <CohortBuilder objectives={objectiveKeys} /> : null}

          <div className="rounded-medium border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-150 py-100">
              <span className="text-body-small font-semibold">Campaign runs</span>
              <span className="text-body-tiny text-text-subtlest">
                a batch of missions with a window and a pace
              </span>
            </div>
            {(campaigns.data ?? []).length === 0 ? (
              <p className="px-150 py-100 text-body-small text-text-subtle">
                No runs. A run groups missions that were already authorised and meters them out; it
                never decides that somebody who should not be called should be.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {(campaigns.data ?? []).map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-100 px-150 py-100">
                    <span className="text-body-small font-medium">{r.name}</span>
                    <span className="font-mono text-body-tiny text-text-subtle">{r.objective}</span>
                    <Lozenge
                      tone={
                        r.status === "running"
                          ? "success"
                          : r.status === "paused"
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {r.status}
                    </Lozenge>
                    <span className="text-body-tiny tabular-nums text-text-subtle">
                      {r.targets_done}/{r.targets_total} · {r.window_start_hour}:00–
                      {r.window_end_hour}:00 · max {r.max_concurrent} at once
                    </span>
                    <span className="ml-auto">
                      <Button
                        size="sm"
                        variant="default"
                        // A cancelled run is as over as a finished one. The
                        // guard named only "finished", so Start stayed live on
                        // a run someone had deliberately stopped — one click
                        // from resuming outbound calls that were cancelled on
                        // purpose, which is the one direction of mistake this
                        // panel cannot afford.
                        disabled={
                          setStatus.isPending || r.status === "finished" || r.status === "cancelled"
                        }
                        onClick={() =>
                          setStatus.mutate({
                            runId: r.id,
                            status: r.status === "running" ? "paused" : "running",
                          })
                        }
                      >
                        {r.status === "running" ? "Pause" : "Start"}
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {pane === "reach" && (
        <div className="space-y-150">
          <p className="max-w-prose text-body-small text-text-subtle">
            None of these could be computed before every dial left a row. A CRM interaction is only
            created once media connects, so a ring-out, a busy tone and a dead number were all
            recorded identically: not at all.
          </p>
          {stats.isLoading ? (
            <LoadingState label="Loading reach" />
          ) : (
            <>
              <div className="grid gap-100 sm:grid-cols-2 lg:grid-cols-4">
                <Stat
                  label="Answer rate"
                  value={pct(stats.data?.answerRate)}
                  hint={`${stats.data?.answered ?? 0} of ${stats.data?.attempts ?? 0} dials`}
                />
                <Stat
                  label="Right party"
                  value={pct(stats.data?.rightPartyRate)}
                  hint="of the calls that were answered"
                />
                <Stat
                  label="Dials per connect"
                  value={
                    stats.data?.attemptsPerConnect ? stats.data.attemptsPerConnect.toFixed(1) : "—"
                  }
                  hint="the dominant term in cost per connect"
                />
                <Stat
                  label="Blocked by policy"
                  value={String(stats.data?.suppressed ?? 0)}
                  hint="refused by the contact gate, not by the borrower"
                />
              </div>
              <p className="text-body-tiny text-text-subtlest">
                Suppressed attempts sit beside these figures, never inside them — a call the gate
                refused is not a call the borrower ignored, and folding the two together would make
                a compliant week look like an unreachable book.
              </p>
            </>
          )}

          <NumberPoolTable />

          <div className="rounded-medium border border-border bg-surface">
            <div className="border-b border-border px-150 py-100 text-body-small font-semibold">
              Why the book is not paying
            </div>
            {(reasons.data ?? []).length === 0 ? (
              <p className="px-150 py-100 text-body-small text-text-subtle">
                Nothing captured yet. The agent records a reason code when the borrower gives one —
                the field the system never had, and the one that says whether a call was worth
                making at all.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {(reasons.data ?? []).map((r) => (
                  <li key={r.reason} className="flex items-center gap-100 px-150 py-100">
                    <span className="text-body-small">{REASON_LABEL[r.reason] ?? r.reason}</span>
                    {r.reason === "forgot" ? (
                      <Lozenge tone="warning">an SMS would have cured these</Lozenge>
                    ) : null}
                    <span className="ml-auto text-body-small tabular-nums text-text-subtle">
                      {r.calls} call(s) · {r.resolved} resolved
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {pane === "aftercall" && (
        <div className="space-y-150">
          <p className="max-w-prose text-body-small text-text-subtle">
            Every finished call gets a structured outcome on two axes — did the phone connect, and
            did the conversation work. Splitting them is what makes a no-answer retryable and a
            refusal not.
          </p>
          {vocab ? (
            <PostCallEditor
              card={card}
              onChange={onChange ?? (() => {})}
              vocab={vocab}
              editable={editable}
            />
          ) : null}
          <div className="rounded-medium border border-border bg-surface">
            <div className="border-b border-border px-150 py-100 text-body-small font-semibold">
              Promises the agent made
            </div>
            {obligations.isLoading ? (
              <div className="px-150 py-100">
                <LoadingState label="Loading obligations" />
              </div>
            ) : (obligations.data ?? []).length === 0 ? (
              <p className="px-150 py-100 text-body-small text-text-subtle">
                Nothing outstanding. When the agent says &ldquo;I&rsquo;ll call you Tuesday at
                six&rdquo;, that becomes a row somebody owes — an agent that keeps its promises is
                the whole trust proposition of an automated line.
              </p>
            ) : (
              <ul className="divide-y divide-border">
                {(obligations.data ?? []).map((o) => (
                  <li key={o.id} className="flex flex-wrap items-center gap-100 px-150 py-100">
                    <span className="text-body-small font-medium">
                      {o.customer_name ?? o.customer_id}
                    </span>
                    <Lozenge tone="information">{o.kind}</Lozenge>
                    <span className="text-body-tiny text-text-subtle">
                      due {new Date(o.due_at).toLocaleString()}
                    </span>
                    {o.verbatim ? (
                      <span className="w-full truncate text-body-tiny italic text-text-subtlest">
                        &ldquo;{o.verbatim}&rdquo;
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
