import { CheckCircle2, Circle, Lock, ShieldCheck } from "lucide-react";
import type { ComplianceItem } from "@/api/handoff";
import { useConfirm } from "@/components/ui/use-confirm";

type Props = {
  items: ComplianceItem[];
  /** Record an item read (or unread). The page shows what the server keeps. */
  onToggle: (item: ComplianceItem, read: boolean) => void;
  /** The item whose write is in flight. */
  pendingId?: string | null;
  readOnly?: boolean;
};

const IDENTITY_RULE = "rule-identity";

/**
 * The checklist as the server has it: what the bot said on the call (its
 * evidence, locked) and what the person working the case attests they told
 * the customer on the follow-up -- a tick filed under their name, shown only
 * once the write succeeds. Identity is not a tick: confirming it files a
 * manual verification, and once verified it cannot be undone.
 */
export function ComplianceChecklist({ items, onToggle, pendingId, readOnly }: Props) {
  const { confirm, confirmDialog } = useConfirm();
  const total = items.filter((i) => i.required).length;
  const done = items.filter((i) => i.required && i.checked).length;
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);

  return (
    <div className="rounded-large border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-150 py-100">
        <h2 className="flex items-center gap-075 text-body-small font-semibold text-text">
          <ShieldCheck className="h-3.5 w-3.5 text-text-success" />
          Compliance
        </h2>
        <span className="tabular text-body-small text-text-subtle">
          {done}/{total} required
        </span>
      </div>
      <p className="px-150 pt-100 text-body-small text-text-subtlest">
        Tick what you told the customer on your follow-up: each tick is your attestation. What the
        bot said on the call is shown as the bot's and can't be changed here.
      </p>
      <div className="px-150 pt-100">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
          <div
            className="h-full rounded-full bg-background-success transition-all"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <ul className="px-050 py-050">
        {items.map((item) => {
          const identity = item.ruleId === IDENTITY_RULE;
          const locked = item.locked;
          const byBot = item.source === "bot";
          const pending = pendingId === item.id;
          const disabled = readOnly || locked || pending;
          const toggle = async () => {
            if (disabled) return;
            if (identity && !item.checked) {
              const ok = await confirm({
                title: "Record identity verified?",
                description:
                  "This files a manual identity verification for this call. Once recorded it can't be undone.",
                confirmLabel: "Record verification",
                cancelLabel: "Not yet",
              });
              if (!ok) return;
            }
            onToggle(item, !item.checked);
          };
          return (
            <li key={item.id}>
              <button
                type="button"
                role="checkbox"
                aria-checked={item.checked}
                aria-disabled={disabled}
                onClick={() => void toggle()}
                title={
                  locked && identity
                    ? "Verified on this call. A verification can't be undone."
                    : locked && byBot
                      ? "The bot said this on the call. Its evidence can't be changed here."
                      : identity && !item.checked
                        ? "Files a manual identity verification"
                        : undefined
                }
                className="flex w-full items-start gap-100 rounded-medium px-100 py-075 text-left hover:bg-surface-sunken aria-disabled:cursor-not-allowed aria-disabled:hover:bg-transparent"
              >
                {item.checked ? (
                  <CheckCircle2 className="mt-025 h-4 w-4 shrink-0 text-text-success" />
                ) : (
                  <Circle className="mt-025 h-4 w-4 shrink-0 text-text-subtlest" />
                )}
                <span className="text-body-small text-text">
                  {identity && !item.checked ? "Record identity verified" : item.label}
                  {!item.required && (
                    <span className="ml-050 text-body-small text-text-subtlest">(optional)</span>
                  )}
                  {pending && (
                    <span className="ml-050 text-body-small text-text-subtlest">saving…</span>
                  )}
                  {locked ? (
                    <span className="ml-050 inline-flex items-center gap-025 text-body-small text-text-subtlest">
                      <Lock className="h-3 w-3" />
                      {identity ? "verified" : "said by the bot"}
                    </span>
                  ) : item.source === "human" ? (
                    <span className="ml-050 text-body-small text-text-subtlest">attested</span>
                  ) : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {confirmDialog}
    </div>
  );
}
