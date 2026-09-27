/** One decision, end to end: why now, every option, the choice, what happened. */
import { useState } from "react";
import { CheckCircle2, CircleSlash, Flag, Phone, ShieldOff, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import { SectionMessage } from "@/components/ui/section-message";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { fmtInr, fmtRate, humanise } from "@/api/treatment";
import {
  groupLabel,
  triggerLabel,
  useDecisionFeedback,
  useExplainDecision,
  useDecisionTrace,
  type DecisionTrace,
  type Evidence,
  type TraceOption,
} from "@/api/treatment-trace";
import { fmtDateTime, fmtRelative } from "@/lib/format";

import { StateGate } from "./chrome";

export function DecisionTraceSheet({
  decisionId,
  onClose,
}: {
  decisionId: string | null;
  onClose: () => void;
}) {
  const trace = useDecisionTrace(decisionId);
  return (
    <Sheet open={Boolean(decisionId)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>Why the engine decided this</SheetTitle>
          <SheetDescription>
            Read from what was recorded at the time and what the decision led to. Nothing here is
            recomputed.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-200">
          <StateGate query={trace} loadingLabel="Loading the decision">
            {(t) => <TraceBody t={t} />}
          </StateGate>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-100 border-t border-border pt-200">
      <h3 className="heading-xsmall text-text">{title}</h3>
      {children}
    </section>
  );
}

export function TraceBody({ t }: { t: DecisionTrace }) {
  const scored = t.options
    .filter((o) => o.status === "scored")
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const blocked = t.options.filter((o) => o.status === "blocked");
  const skipped = t.options.filter((o) => o.status === "not_considered");
  const shadowOnly = t.choice.holdReason === "shadow_mode";
  return (
    <div className="flex flex-col gap-200">
      <Headline t={t} shadowOnly={shadowOnly} />

      <Section title="Why now">
        <p className="text-body-small text-text-subtle">
          Because: <span className="text-text">{triggerLabel(t.whyNow.trigger)}</span>
          {t.whyNow.triggerRef && !t.whyNow.triggerRef.startsWith("manual:") ? ` (${t.whyNow.triggerRef})` : ""} · decided{" "}
          {fmtDateTime(t.createdAt)}
        </p>
        <dl className="grid grid-cols-1 gap-x-300 gap-y-050 text-body-small sm:grid-cols-2">
          {t.whyNow.facts.map((f) => (
            <div key={f.key} className="flex justify-between gap-100 border-b border-border py-050">
              <dt className="text-text-subtle">{f.label}</dt>
              <dd className="text-right tabular-nums text-text">{fmtFact(f.key, f.value)}</dd>
            </div>
          ))}
        </dl>
        <Feeds feeds={t.whyNow.dataFreshness} />
      </Section>

      <Section title="Options considered">
        <ul className="flex flex-col gap-100">
          {scored.map((o) => (
            <ScoredOption key={o.action} o={o} />
          ))}
        </ul>
        {blocked.length > 0 && (
          <>
            <h4 className="mt-100 text-body-small font-semibold text-text-subtle">Blocked before scoring</h4>
            <ul className="flex flex-col gap-050">
              {blocked.map((o) => (
                <li key={o.action} className="flex items-start gap-100 text-body-small">
                  <ShieldOff aria-hidden className="mt-025 size-3.5 shrink-0 text-icon-subtle" />
                  <span>
                    <span className="font-medium text-text">{humanise(o.label)}</span>
                    <span className="text-text-subtle">: {o.reason}</span>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
        {skipped.length > 0 && (
          <p className="text-body-tiny text-text-subtlest">
            Not offered on this trigger: {skipped.map((o) => o.label).join(", ")}.
          </p>
        )}
      </Section>

      <Section title="What happened">
        <Happened t={t} />
      </Section>

      <Section title="Record">
        <dl className="grid grid-cols-1 gap-x-300 gap-y-050 text-body-tiny sm:grid-cols-2">
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtle">Decision id</dt>
            <dd className="tabular-nums text-text">{t.id}</dd>
          </div>
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtle">Mode</dt>
            <dd className="text-text">{humanise(t.mode)}</dd>
          </div>
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtle">Group</dt>
            <dd className="text-text">{groupLabel(t.variant)}</dd>
          </div>
          {Object.entries(t.versions).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-100">
              <dt className="text-text-subtle">{humanise(k)}</dt>
              <dd className="truncate tabular-nums text-text">{v == null ? "—" : String(v)}</dd>
            </div>
          ))}
        </dl>
        <Feedback t={t} />
      </Section>
    </div>
  );
}

function Headline({ t, shadowOnly }: { t: DecisionTrace; shadowOnly: boolean }) {
  const c = t.choice;
  const held = c.held && !shadowOnly;
  const explain = useExplainDecision();
  return (
    <div className="flex flex-col gap-100 rounded-large border border-border bg-surface p-200">
      <div className="flex flex-wrap items-center gap-100">
        <span className="heading-small text-text">
          {held ? "Hold" : humanise(c.label)}
          {!held && c.scheduledAt ? ` · ${fmtDateTime(c.scheduledAt)}` : ""}
        </span>
        {t.customerName ? <Lozenge>{t.customerName}</Lozenge> : null}
        {shadowOnly ? (
          <Lozenge tone="information">Recommended, not carried out (shadow)</Lozenge>
        ) : held ? (
          <Lozenge tone="warning">Held</Lozenge>
        ) : t.happened.enacted ? (
          <Lozenge tone="success">Carried out</Lozenge>
        ) : (
          <Lozenge tone="information">Planned</Lozenge>
        )}
      </div>
      {held ? (
        <p className="text-body text-text">Why: {c.holdReasonText}</p>
      ) : (
        <p className="text-body text-text">
          How it was picked: {c.howText}
          {c.pickProbability != null && c.how === "ranked"
            ? ` (picked with ${fmtRate(c.pickProbability)} probability)`
            : ""}
          {c.beat
            ? `. It beat ${humanise(c.beat.label)} by ${fmtInr(c.beat.byInr)} of expected value.`
            : "."}
        </p>
      )}
      {c.rationale ? <p className="text-body-small text-text-subtle">{c.rationale}</p> : null}
      {explain.data ? (
        <p className="rounded-medium bg-background-neutral p-150 text-body text-text">
          {explain.data.text}
          <span className="ml-075 text-body-tiny text-text-subtlest">
            {explain.data.source === "llm" ? "AI explanation, written only from this record" : "rule-written"}
          </span>
        </p>
      ) : (
        <div>
          <Button size="sm" variant="outline" disabled={explain.isPending} onClick={() => explain.mutate(t.id)}>
            <Sparkles className="mr-075 h-3.5 w-3.5" /> {explain.isPending ? "Explaining…" : "Explain in plain words"}
          </Button>
        </div>
      )}
    </div>
  );
}

function evidenceText(e: Evidence | undefined): string {
  if (!e) return "";
  if (e.source === "history") return "this borrower's own history";
  if (e.source === "delivery") return "delivered, not answered";
  if (e.source === "learned")
    return `learned: ${e.successes ?? 0} of ${e.trials ?? 0} in ${e.windowDays ?? 90} days, starting from ${fmtRate(e.prior)}`;
  return "starting assumption (no outcomes yet)";
}

function ScoredOption({ o }: { o: TraceOption }) {
  return (
    <li
      className={`rounded-medium border p-150 ${o.chosen ? "border-border-brand bg-background-selected" : "border-border"}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-100">
        <span className="text-body font-medium text-text">
          {o.rank}. {humanise(o.label)}
          {o.chosen ? (
            <CheckCircle2 aria-label="chosen" className="ml-050 inline size-4 text-icon-success" />
          ) : null}
        </span>
        <span className="text-body-small tabular-nums text-text">
          {fmtInr(o.expectedValue ?? null)} expected
        </span>
      </div>
      {o.explanation ? <p className="text-body-small text-text-subtle">{o.explanation}</p> : null}
      {o.action !== "wait" && (
        <ul className="mt-050 grid gap-025 text-body-tiny text-text-subtle">
          <li>
            Reach {fmtRate(o.pReach ?? null)} · {evidenceText(o.evidence?.reach)}
          </li>
          <li>
            Cure if reached {fmtRate(o.pResolve ?? null)} · {evidenceText(o.evidence?.resolve)}
          </li>
          <li>
            Costs {fmtInr(o.cost ?? null)}
            {o.timingRationale ? ` · timed for ${o.timingRationale}` : ""}
          </li>
        </ul>
      )}
    </li>
  );
}

function Feeds({ feeds }: { feeds: DecisionTrace["whyNow"]["dataFreshness"] }) {
  if (feeds.length === 0) return null;
  const missing = feeds.filter((f) => !f.lastReceivedAt);
  return (
    <p className="text-body-tiny text-text-subtle">
      Bank data feeds:{" "}
      {feeds
        .map((f) => `${f.name ?? f.feed} ${f.lastReceivedAt ? fmtRelative(f.lastReceivedAt) : "never received"}`)
        .join(" · ")}
      {missing.length > 0 ? ". A missing or stale feed blocks contact." : ""}
    </p>
  );
}

function Happened({ t }: { t: DecisionTrace }) {
  const h = t.happened;
  const lines: React.ReactNode[] = [];
  if (h.enacted) lines.push(`Carried out ${fmtDateTime(h.enactedAt)} by ${humanise(h.enactedBy)}.`);
  else if (h.cancelReason) lines.push(`Not carried out: ${humanise(h.cancelReason)}.`);
  for (const c of h.calls) {
    lines.push(
      <span key={c.id} className="inline-flex flex-wrap items-center gap-050">
        <Phone aria-hidden className="size-3.5" /> Call {humanise(c.state)}
        {c.duration_sec ? `, ${c.duration_sec}s` : ""}
        {c.disposition ? `, ended at "${humanise(c.disposition)}"` : ""}
        {c.business ? `, outcome ${humanise(c.business)}` : ""}
        {c.interaction_id ? (
          <a className="text-link underline" href={`/audit?id=${encodeURIComponent(c.interaction_id)}`}>
            transcript
          </a>
        ) : null}
        {c.summary ? <span className="block text-text-subtle">{c.summary}</span> : null}
      </span>,
    );
  }
  for (const m of h.messages) lines.push(`WhatsApp ${humanise(m.status)} ${fmtDateTime(m.created_at)}.`);
  for (const p of h.promisesSince)
    lines.push(`Promise ${fmtInr(p.amount)} for ${fmtDateTime(p.promised_at)}: ${humanise(p.status)}.`);
  for (const p of h.paymentsSince) lines.push(`Payment ${fmtInr(p.amount)} on ${fmtDateTime(p.posted_at)}.`);
  const label = h.label;
  return (
    <div className="flex flex-col gap-100">
      {lines.length === 0 ? (
        <p className="text-body-small text-text-subtle">Nothing yet.</p>
      ) : (
        <ul className="flex flex-col gap-050 text-body-small text-text">
          {lines.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
      {label.outcome ? (
        <SectionMessage variant="information" icon={Sparkles} title={`Recorded outcome: ${humanise(label.outcome)}`}>
          Reached: {humanise(label.reach)} · cured: {label.cure ? humanise(label.cure) : "still open"}
          {label.matureAt ? ` (final by ${fmtDateTime(label.matureAt)})` : ""}. This is what the engine
          learns from.
        </SectionMessage>
      ) : (
        <p className="text-body-tiny text-text-subtlest">
          <CircleSlash aria-hidden className="mr-025 inline size-3" />
          No outcome recorded yet; it is labelled once the result is knowable.
        </p>
      )}
    </div>
  );
}

function Feedback({ t }: { t: DecisionTrace }) {
  const feedback = useDecisionFeedback();
  const [sent, setSent] = useState<string | null>(null);
  const verdicts = [
    ["wrong_number", "Wrong number"],
    ["stop_contact", "Customer asked to stop"],
    ["deceased", "Customer deceased"],
    ["other", "Something else is wrong"],
  ] as const;
  return (
    <div className="flex flex-col gap-100">
      {t.feedback.length > 0 && (
        <ul className="flex flex-col gap-025 text-body-tiny text-text-subtle">
          {t.feedback.map((f, i) => (
            <li key={i}>
              {fmtDateTime(f.created_at)} · {humanise(f.verdict)}
              {f.actor_role ? ` by ${f.actor_role}` : ""}
              {f.note_redacted ? `: ${f.note_redacted}` : ""}
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-075">
        <Flag aria-hidden className="size-3.5 text-icon-subtle" />
        <span className="text-body-tiny text-text-subtle">Correct the record:</span>
        {verdicts.map(([v, label]) => (
          <Button
            key={v}
            size="sm"
            variant="outline"
            disabled={feedback.isPending}
            onClick={() =>
              feedback.mutate({ decisionId: t.id, verdict: v }, { onSuccess: () => setSent(label) })
            }
          >
            {label}
          </Button>
        ))}
      </div>
      {sent ? <p className="text-body-tiny text-text-success">Recorded: {sent}. The engine will hold accordingly.</p> : null}
    </div>
  );
}

function fmtFact(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    if (["exposure", "outstanding", "instalmentAmount"].includes(key)) return fmtInr(value);
    return value.toLocaleString("en-IN");
  }
  if (Array.isArray(value)) return value.length ? value.map((v) => humanise(String(v))).join(", ") : "none";
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return "none";
    return entries
      .map(
        ([k, v]) =>
          `${humanise(k)} ${v == null ? "no history" : typeof v === "number" && v <= 1 ? fmtRate(v, 0) : humanise(String(v))}`,
      )
      .join(", ");
  }
  return humanise(String(value));
}
