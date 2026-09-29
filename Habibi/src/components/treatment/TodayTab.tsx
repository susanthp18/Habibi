/** Today: is the engine running, what did it decide, and what is stopping it. */
import { AlertTriangle, CheckCircle2, CircleSlash, Clock } from "lucide-react";

import { Lozenge } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import { fmtInr, fmtNum, humanise, useTreatmentInsights } from "@/api/treatment";
import { useTreatmentHealth, type StageHealth } from "@/api/treatment-trace";
import { fmtRelative } from "@/lib/format";

import { BarList, Panel, Stat, StateGate } from "./chrome";

const STATUS = {
  ok: { tone: "success", icon: CheckCircle2, text: "Running" },
  late: { tone: "warning", icon: Clock, text: "Late" },
  never: { tone: "danger", icon: CircleSlash, text: "Never ran" },
} as const;

export function TodayTab({ days }: { days: number }) {
  // Health looks back at most 30 days (GET /treatment/health le=30); the page's
  // 90-day window applies to the insights below.
  const health = useTreatmentHealth(Math.min(days, 30));
  const insights = useTreatmentInsights(days);
  return (
    <div className="flex flex-col gap-200">
      <StateGate query={health} loadingLabel="Checking the engine">
        {(h) => (
          <>
            <ModeBanner mode={h.mode} enactOn={h.enactSwitchOn} />
            <Panel
              title="Is it running?"
              description="Each stage of the engine and when it last ran. Anything late or never run means the screen below is out of date."
            >
              <ul className="grid gap-100 md:grid-cols-2 xl:grid-cols-4">
                {h.stages.map((s) => (
                  <StageCard key={s.key} s={s} />
                ))}
              </ul>
            </Panel>
            {h.blockers.length > 0 && (
              <Panel
                title="What is stopping contact"
                description={`Why options were ruled out for borrowers in the last ${days === 1 ? "day" : `${days} days`}.`}
              >
                <ul className="flex flex-col gap-075">
                  {h.blockers.map((b) => (
                    <li key={b.code} className="flex items-baseline justify-between gap-150 text-body-small">
                      <span className="text-text">{b.text.charAt(0).toUpperCase() + b.text.slice(1)}</span>
                      <span className="shrink-0 tabular-nums text-text-subtle">
                        {fmtNum(b.borrowers)} borrowers
                      </span>
                    </li>
                  ))}
                </ul>
                <FeedNote feeds={h.feeds} />
              </Panel>
            )}
          </>
        )}
      </StateGate>

      <StateGate
        query={insights}
        loadingLabel="Loading decisions"
        isEmpty={(d) => d.decisions === 0}
        emptyTitle="No decisions in this window"
        emptyBody="Nothing triggered a decision: no bounces, no broken promises, and the daily sweep has not run. Check the stages above."
      >
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-150 md:grid-cols-5">
              <Stat label="Decisions" value={fmtNum(d.decisions)} hint={`${fmtNum(d.customers)} borrowers`} />
              <Stat label="Would act" value={fmtNum(d.actionable)} hint="chose something other than waiting" />
              <Stat label="Carried out" value={fmtNum(d.enacted)} />
              <Stat
                label="Held"
                value={fmtNum(d.suppression.reduce((n, s) => n + s.count, 0))}
                hint="rules, holds or shadow mode"
              />
              <Stat label="Expected value" value={fmtInr(d.expectedValueInr)} hint="latest decision per case" />
            </div>
            <div className="grid gap-200 lg:grid-cols-3">
              <Panel title="What it chose" description="The action picked, when it picked one.">
                <BarList rows={d.byAction.map((a) => ({ key: a.action, label: humanise(a.action), count: a.count }))} />
              </Panel>
              <Panel title="Why it held" description="Decisions that ended in waiting, by reason.">
                {d.suppression.length ? (
                  <BarList rows={d.suppression.map((s) => ({ key: s.reason, label: humanise(s.reason), count: s.count }))} />
                ) : (
                  <p className="text-body-small text-text-subtle">Nothing was held.</p>
                )}
              </Panel>
              <Panel title="What happened next" description="Recorded outcomes of these decisions.">
                {d.outcomes.length ? (
                  <BarList rows={d.outcomes.map((o) => ({ key: o.outcome, label: humanise(o.outcome), count: o.count }))} />
                ) : (
                  <p className="text-body-small text-text-subtle">No outcomes recorded yet.</p>
                )}
              </Panel>
            </div>
          </>
        )}
      </StateGate>
    </div>
  );
}

function ModeBanner({ mode, enactOn }: { mode: string; enactOn: boolean }) {
  if (mode === "live" && enactOn) {
    return (
      <SectionMessage variant="success" icon={CheckCircle2} title="Live: decisions are carried out">
        Calls, messages and work items go out as the engine decides, within the contact rules.
      </SectionMessage>
    );
  }
  const why =
    mode === "live"
      ? "The engine is live but the “treatment executor” switch in Platform settings is off, so nothing is carried out."
      : mode === "off"
        ? "The engine is switched off: nothing is decided or carried out."
        : "Shadow mode: the engine decides and records every decision, and carries none of them out. Read the decisions, then switch to live.";
  return (
    <SectionMessage variant="warning" icon={AlertTriangle} title={`${humanise(mode)} mode`}>
      {why}
    </SectionMessage>
  );
}

function StageCard({ s }: { s: StageHealth }) {
  const st = STATUS[s.status];
  const Icon = st.icon;
  const result = s.lastResult?.result as { tail?: string[]; error?: string } | undefined;
  const refused = s.lastResult && s.lastResult.status !== "completed";
  return (
    <li className="flex flex-col gap-050 rounded-medium border border-border p-150">
      <div className="flex items-center justify-between gap-100">
        <span className="text-body font-medium text-text">{s.label}</span>
        <Lozenge tone={st.tone}>
          <Icon aria-hidden /> {st.text}
        </Lozenge>
      </div>
      <p className="text-body-tiny text-text-subtle">{s.does}</p>
      <p className="text-body-tiny text-text-subtlest">
        {s.lastAt ? `Last: ${fmtRelative(s.lastAt)}` : "No run on record"}
      </p>
      {refused && result?.tail?.length ? (
        <p className="line-clamp-3 text-body-tiny text-text-warning" title={result.tail.join("\n")}>
          {result.tail[result.tail.length - 1]}
        </p>
      ) : null}
    </li>
  );
}

function FeedNote({
  feeds,
}: {
  feeds: Array<{ feed: string; name?: string; lastReceivedAt: string | null }>;
}) {
  const missing = feeds.filter((f) => !f.lastReceivedAt).map((f) => f.name ?? f.feed);
  if (missing.length === 0) return null;
  return (
    <p className="mt-100 text-body-tiny text-text-subtle">
      Bank feeds never received: {missing.join(", ")}. Contact stays blocked until the bank sends them.
    </p>
  );
}
