import { useState } from "react";
import { Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Lozenge, type LozengeTone } from "@/components/ui/lozenge";
import {
  usePolicyRuleSetAction,
  usePolicyRuleSets,
  type PolicyRuleSet,
  type PolicyRuleSetState,
} from "@/api/compliance";
import { can, useMe } from "@/api/me";

/**
 * The statutory rule sets the contact gate resolves against, and their
 * maker-checker publication.
 *
 * Until a set is published the gate runs on module constants and every
 * decision stamps no policy_version, so "under which rules did you dial?" has
 * no answer. The approver reads the rules and their citations here, not a
 * label, and cannot approve a set they submitted themselves.
 */

const STATE: Record<PolicyRuleSetState, { tone: LozengeTone; label: string }> = {
  draft: { tone: "neutral", label: "draft" },
  pending_approval: { tone: "warning", label: "awaiting approval" },
  published: { tone: "success", label: "published" },
  rejected: { tone: "danger", label: "rejected" },
};

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : null);

function describe(rule: PolicyRuleSet["rules"][number]): string {
  const p = rule.params;
  switch (rule.kind) {
    case "calling_window":
      return `${rule.channel ?? "all"} calls only ${String(p.startHour).padStart(2, "0")}:00–${String(p.endHour).padStart(2, "0")}:00`;
    case "recording_retention":
      return `keep recordings ${String(p.months)} months`;
    case "visit_intimation":
      return `notify ${String(p.hours)} h before a field visit`;
    case "mandate_return_action": {
      const veto = Object.entries((p.byReason as Record<string, string>) ?? {})
        .filter(([, v]) => v === "veto")
        .map(([k]) => k.replace(/_/g, " "));
      return veto.length ? `no re-presentment after ${veto.join(", ")}` : "mandate returns allowed";
    }
    default:
      return `${rule.kind}${rule.channel ? ` (${rule.channel})` : ""}`;
  }
}

export function StatutoryRulesCard() {
  const { data, isLoading, isError } = usePolicyRuleSets();
  const { data: me } = useMe();
  const action = usePolicyRuleSetAction();

  if (isLoading || isError || !data) return null;
  const sets = data.filter((s) => s.scope === "statutory");
  // Statutory sets bind every tenant, so the database admits their writes
  // only in platform scope -- which the server grants on perm-platform-write.
  const platform = can(me, "perm-platform-write");
  const canPublish = platform && can(me, "perm-policy-publish");
  const canApprove = platform && can(me, "perm-policy-approve");
  const busy = (id: string) => action.isPending && action.variables?.id === id;

  return (
    <section className="rounded-medium border border-border bg-surface p-150">
      <div className="mb-100 flex items-center gap-075">
        <Scale aria-hidden className="size-4 text-text-subtle" />
        <h2 className="text-body font-semibold text-text">Statutory rules</h2>
      </div>
      {sets.length === 0 ? (
        <p className="text-body-small text-text-subtle">
          No statutory rule set exists. The contact gate runs on built-in defaults and records no
          policy version.
        </p>
      ) : (
        <ul className="space-y-150">
          {sets.map((s) => {
            const state = s.publication_state ?? "published";
            const mine = Boolean(me?.id) && s.published_by_user_id === me?.id;
            return (
              <li key={s.id} className="space-y-075 text-body-small">
                <div className="flex flex-wrap items-center gap-075">
                  <span className="font-semibold text-text">v{s.version}</span>
                  <Lozenge tone={STATE[state].tone}>{STATE[state].label}</Lozenge>
                  <span className="text-text-subtlest">
                    {day(s.effective_from)} → {day(s.effective_to) ?? "in force"}
                  </span>
                </div>
                <div className="text-text-subtle">{s.label}</div>
                <ul className="list-disc space-y-025 pl-200 text-text">
                  {s.rules.map((r) => (
                    <li key={`${r.kind}-${r.channel ?? "all"}`}>{describe(r)}</li>
                  ))}
                </ul>
                {s.notes ? <p className="text-text-subtlest">{s.notes}</p> : null}
                <div className="flex flex-wrap items-center gap-075">
                  {(state === "draft" || state === "rejected") && canPublish ? (
                    <Button
                      size="sm"
                      disabled={busy(s.id)}
                      onClick={() => action.mutate({ id: s.id, action: "submit" })}
                    >
                      Submit for approval
                    </Button>
                  ) : null}
                  {state === "pending_approval" && canApprove && !mine ? (
                    <>
                      <Button
                        size="sm"
                        disabled={busy(s.id)}
                        onClick={() => action.mutate({ id: s.id, action: "approve" })}
                      >
                        Approve and publish
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy(s.id)}
                        onClick={() => action.mutate({ id: s.id, action: "reject" })}
                      >
                        Reject
                      </Button>
                    </>
                  ) : null}
                  {!platform && state !== "published" ? (
                    <span className="text-text-subtlest">
                      Platform-wide: a platform administrator submits and approves it.
                    </span>
                  ) : null}
                  {state === "pending_approval" && mine && !s.selfApprovable ? (
                    <span className="text-text-subtlest">
                      You submitted this; a different approver must publish it.
                    </span>
                  ) : null}
                  {state === "pending_approval" && mine && s.selfApprovable && canApprove ? (
                    <BreakGlassApprove
                      busy={busy(s.id)}
                      onApprove={(reason) =>
                        action.mutate({ id: s.id, action: "approve", selfApprovalReason: reason })
                      }
                    />
                  ) : null}
                  {state === "published" &&
                  s.approved_by_user_id &&
                  s.approved_by_user_id === s.published_by_user_id ? (
                    <>
                      <Lozenge tone="warning">self-approved (break-glass)</Lozenge>
                      {s.self_approval_reason ? (
                        <span className="text-text-subtle">“{s.self_approval_reason}”</span>
                      ) : null}
                    </>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const MIN_REASON = 20;

/**
 * The maker approving their own set. Offered only where the server says this
 * viewer may (POLICY_SELF_APPROVE_USERS), and never without a written reason:
 * the reason goes onto the audit chain beside "breakGlass".
 */
function BreakGlassApprove({
  busy,
  onApprove,
}: {
  busy: boolean;
  onApprove: (reason: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const ready = reason.trim().length >= MIN_REASON;
  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Approve my own submission (break-glass)
      </Button>
    );
  }
  return (
    <div className="w-full space-y-075 rounded-medium border border-border-warning bg-background-warning-subtler p-100">
      <label
        htmlFor="break-glass-reason"
        className="block text-body-small font-semibold text-text-warning-bolder"
      >
        Why are four eyes being waived?
      </label>
      <textarea
        id="break-glass-reason"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={3}
        className="w-full rounded-medium border border-border bg-surface p-075 text-body-small text-text"
        placeholder="Recorded permanently on the audit log with your name."
      />
      <div className="flex flex-wrap items-center gap-075">
        <Button size="sm" disabled={!ready || busy} onClick={() => onApprove(reason.trim())}>
          Self-approve and publish
        </Button>
        <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
        {!ready ? (
          <span className="text-text-subtlest">At least {MIN_REASON} characters.</span>
        ) : null}
      </div>
    </div>
  );
}
