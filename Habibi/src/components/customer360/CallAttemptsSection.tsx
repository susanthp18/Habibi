import { ATTEMPT_STATE_LABEL, useOutboundAttempts, type CallAttempt } from "@/api/outbound";
import type { Customer } from "@/api/types/customer360";
import { Empty } from "@/components/ui/empty";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import { QueryState } from "@/components/ui/query-state";
import { fmtDateTime, fmtRelative } from "@/lib/format";

function tone(state: string): LozengeTone {
  if (state === "suppressed" || state === "failed" || state === "invalid_number") return "danger";
  if (state === "completed" || state === "answered" || state === "live") return "success";
  if (state === "reserved" || state === "dialing" || state === "ringing") return "information";
  return "neutral";
}

/** `customer_dnd` → "customer dnd": the codes are the policy's, the reader is a person. */
const words = (code: string) => code.replace(/_/g, " ");

function detail(a: CallAttempt): string {
  const bits: string[] = [];
  if (a.suppressed_reason) bits.push(`blocked: ${words(a.suppressed_reason)}`);
  if (a.business) bits.push(words(a.business));
  if (a.ring_sec != null) bits.push(`rang ${a.ring_sec}s`);
  if (a.talk_sec) bits.push(`talked ${a.talk_sec}s`);
  if (a.provider_error) bits.push(`carrier ${a.provider_error}`);
  return bits.join(" · ");
}

/**
 * Every dial to this borrower, including the ones that never connected.
 *
 * An interaction row only exists once media connects, so a refused, ring-out
 * or busy attempt was invisible here; "why did nobody reach them on Tuesday"
 * had an answer in `call_attempts` and nowhere on screen.
 */
export function CallAttemptsSection({ customer }: { customer: Customer }) {
  const attempts = useOutboundAttempts(customer.id);
  const rows = attempts.data ?? [];

  return (
    <section className="space-y-100">
      <h3 className="text-body-small font-semibold">Call attempts</h3>
      <QueryState
        query={attempts}
        label="call attempts"
        empty={
          rows.length === 0 ? (
            <Empty title="No call attempts">Nobody has dialled this borrower yet.</Empty>
          ) : null
        }
      >
        {rows.length > 0 && (
          <ul className="divide-y divide-border rounded-medium border border-border bg-surface">
            {rows.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-100 px-150 py-100">
                <Lozenge tone={tone(a.state)}>{ATTEMPT_STATE_LABEL[a.state] ?? words(a.state)}</Lozenge>
                <span className="font-mono text-body-tiny text-text-subtle">{a.objective}</span>
                <span className="text-body-small text-text-subtle">{detail(a)}</span>
                <span
                  className="ml-auto text-body-tiny text-text-subtlest"
                  title={fmtDateTime(a.reserved_at)}
                >
                  {fmtRelative(a.reserved_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
    </section>
  );
}
