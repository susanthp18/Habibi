/** One offer, end to end: the customer's words, the choice, the checks, the delivery. */
import { CheckCircle2, MessageSquareQuote, ShieldOff, ThumbsDown, ThumbsUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Lozenge } from "@/components/ui/lozenge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { StateGate } from "@/components/treatment/chrome";
import { fmtInr, fmtRate, humanise } from "@/api/treatment";
import {
  useOfferTrace,
  useSignalFeedback,
  type CustomerSignal,
  type OfferTrace,
} from "@/api/offer-trace";
import { fmtDateTime } from "@/lib/format";

export function OfferTraceSheet({ decisionId, onClose }: { decisionId: string | null; onClose: () => void }) {
  const trace = useOfferTrace(decisionId);
  return (
    <Sheet open={Boolean(decisionId)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-3xl">
        <SheetHeader>
          <SheetTitle>Why this offer</SheetTitle>
          <SheetDescription>
            What the customer said, every product considered and why, the suitability finding, and
            whether it was sent.
          </SheetDescription>
        </SheetHeader>
        <div className="mt-200">
          <StateGate query={trace} loadingLabel="Loading the offer">
            {(t) => <OfferTraceBody t={t} />}
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

export function SignalRow({ s }: { s: CustomerSignal }) {
  const feedback = useSignalFeedback();
  return (
    <li className="flex flex-col gap-050 rounded-medium border border-border p-150">
      <div className="flex flex-wrap items-center justify-between gap-100">
        <span className="text-body-small font-medium text-text">{s.label}</span>
        <span className="text-body-tiny text-text-subtlest">
          {humanise(s.channel)} · {fmtDateTime(s.createdAt)} · {fmtRate(s.confidence, 0)} sure
          {s.horizon && s.horizon !== "unknown" ? ` · ${humanise(s.horizon)}` : ""}
        </span>
      </div>
      {s.evidence ? (
        <p className="text-body-small text-text-subtle">
          <MessageSquareQuote aria-hidden className="mr-050 inline size-3.5" />“{s.evidence}”
        </p>
      ) : null}
      <div className="flex items-center gap-075">
        {s.feedback ? (
          <Lozenge tone={s.feedback === "right" ? "success" : "danger"}>
            Marked {s.feedback}
          </Lozenge>
        ) : (
          <>
            <span className="text-body-tiny text-text-subtlest">Is this right?</span>
            <Button
              size="sm"
              variant="outline"
              disabled={feedback.isPending}
              onClick={() => feedback.mutate({ signalId: s.id, verdict: "right" })}
            >
              <ThumbsUp className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={feedback.isPending}
              onClick={() => feedback.mutate({ signalId: s.id, verdict: "wrong" })}
            >
              <ThumbsDown className="h-3.5 w-3.5" />
            </Button>
          </>
        )}
      </div>
    </li>
  );
}

export function OfferTraceBody({ t }: { t: OfferTrace }) {
  const c = t.choice;
  const d = t.delivery;
  const scored = t.options.filter((o) => o.status === "scored");
  const blocked = t.options.filter((o) => o.status === "blocked");
  return (
    <div className="flex flex-col gap-200">
      <div className="flex flex-col gap-100 rounded-large border border-border bg-surface p-200">
        <div className="flex flex-wrap items-center gap-100">
          <span className="heading-small text-text">{c.held || !c.name ? "No offer" : c.name}</span>
          {t.customerName ? <Lozenge>{t.customerName}</Lozenge> : null}
          <Lozenge tone="information">{t.context === "promotional" ? "From what they said" : "Scored on a call"}</Lozenge>
          {d.response ? (
            <Lozenge tone={d.response === "interested" ? "success" : "neutral"}>{humanise(d.response)}</Lozenge>
          ) : d.presented ? (
            <Lozenge tone="success">Sent</Lozenge>
          ) : null}
        </div>
        {c.held || !c.name ? (
          <p className="text-body text-text">Why: {c.holdReasonText || "nothing was suitable and eligible"}</p>
        ) : (
          <p className="text-body text-text">
            {c.suggestedAmount != null ? `Indicative ${fmtInr(c.suggestedAmount)}. ` : ""}
            Decided {fmtDateTime(t.createdAt)}.
          </p>
        )}
      </div>

      <Section title="What the customer said">
        {t.signals.length ? (
          <ul className="flex flex-col gap-100">
            {t.signals.map((s) => (
              <SignalRow key={s.id} s={s} />
            ))}
          </ul>
        ) : (
          <p className="text-body-small text-text-subtle">This decision cited no signals.</p>
        )}
      </Section>

      <Section title="Products considered">
        <ul className="flex flex-col gap-075">
          {scored.map((o) => (
            <li key={o.productId} className="text-body-small">
              <span className="font-medium text-text">
                {o.name} {o.chosen ? <CheckCircle2 aria-label="chosen" className="inline size-4 text-icon-success" /> : null}
              </span>
              <span className="text-text-subtle">
                {" "}· score {o.score != null ? Math.round(o.score * 100) : "—"}
                {o.reasonCodes?.some((r) => r.startsWith("signal:"))
                  ? ` · raised by: ${o.reasonCodes.filter((r) => r.startsWith("signal:")).map((r) => humanise(r.slice(7))).join(", ")}`
                  : ""}
              </span>
              {o.explanation ? <span className="block text-body-tiny text-text-subtle">{o.explanation}</span> : null}
            </li>
          ))}
          {blocked.map((o) => (
            <li key={o.productId} className="flex items-start gap-100 text-body-small">
              <ShieldOff aria-hidden className="mt-025 size-3.5 shrink-0 text-icon-subtle" />
              <span>
                <span className="font-medium text-text">{o.name}</span>
                <span className="text-text-subtle">: {o.reason}</span>
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Suitability findings">
        {t.suitability.length ? (
          <ul className="flex flex-col gap-050 text-body-small">
            {t.suitability.map((s) => (
              <li key={`${s.product_id}-${s.assessed_at}`}>
                <span className="font-medium text-text">{s.product_id}</span>{" "}
                <Lozenge tone={s.verdict === "suitable" ? "success" : "warning"}>{s.verdict}</Lozenge>
                <span className="block text-body-tiny text-text-subtle">
                  {s.evidence_ref} · by {s.assessor} · valid to {fmtDateTime(s.expires_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-small text-text-subtle">No finding on file.</p>
        )}
      </Section>

      <Section title="Delivery">
        <ul className="flex flex-col gap-050 text-body-small text-text">
          {d.messages.map((m) => (
            <li key={m.id}>
              WhatsApp {m.template_name ? `template ${m.template_name}` : "message"}: {humanise(m.status)} ·{" "}
              {fmtDateTime(m.created_at)}
            </li>
          ))}
          {d.leads.map((l) => (
            <li key={l.id}>
              Lead {l.id} for a relationship manager: {humanise(l.stage)} · {fmtDateTime(l.created_at)}
            </li>
          ))}
          {!d.messages.length && !d.leads.length ? (
            <li className="text-text-subtle">Not sent yet.</li>
          ) : null}
        </ul>
      </Section>

      <Section title="Record">
        <dl className="grid grid-cols-1 gap-x-300 gap-y-050 text-body-tiny sm:grid-cols-2">
          <div className="flex justify-between gap-100">
            <dt className="text-text-subtle">Decision id</dt>
            <dd className="tabular-nums text-text">{t.id}</dd>
          </div>
          {Object.entries(t.versions).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-100">
              <dt className="text-text-subtle">{humanise(k)}</dt>
              <dd className="truncate text-text">{v == null ? "—" : String(v)}</dd>
            </div>
          ))}
        </dl>
      </Section>
    </div>
  );
}
