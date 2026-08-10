import type { Persona } from "@/data/sandbox-seed";
import type { IdentityVerifiedEvent } from "@/components/sandbox/voice/liveEvents";
import { Lozenge } from "@/components/ui/lozenge";

type Props = {
  persona: Persona;
  scenarioTitle: string;
  /** Present once verify_identity has resolved a real CRM customer. */
  verified?: IdentityVerifiedEvent | null;
};

/**
 * Who is on this call — and, crucially, in which sense.
 *
 * Two different identities live here and the header used to show only the
 * first, which is how a call that had verified "Susanth" against the CRM went
 * on describing itself as "Rahul Sharma":
 *
 *   * the **persona** is a rehearsal script — the name, mood and language the
 *     tester typed in to play the caller. It is not a customer record;
 *   * the **verified customer** is the CRM row every tool returns once identity
 *     checks out, and it is what the bot's answers are actually about.
 *
 * The backend already encodes this precedence (`persona_message` in
 * agent_core/context.py tells the model the CRM record wins once verified).
 * This is the same rule, made visible.
 */
export function PersonaCard({ persona, scenarioTitle, verified }: Props) {
  const verifiedName = verified?.customerName?.trim() || null;
  const headlineName = verifiedName || persona.name;
  const initials =
    headlineName
      .split(" ")
      .map((s) => s[0])
      .slice(0, 2)
      .join("") || "??";

  return (
    <div className="shrink-0 border-b border-border bg-surface-sunken px-200 py-150">
      <div className="flex items-center gap-150">
        <div className="grid h-500 w-500 shrink-0 place-items-center rounded-full bg-background-brand-bold/10 text-body font-semibold text-text-brand">
          {initials}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-100">
            <div className="truncate text-body font-semibold text-text">{headlineName}</div>
            {verifiedName ? (
              <Lozenge tone="success">Verified customer</Lozenge>
            ) : (
              <Lozenge tone="information">Not yet verified</Lozenge>
            )}
          </div>
          <div className="mt-025 flex flex-wrap gap-x-150 gap-y-025 text-body-small text-text-subtlest">
            {verifiedName ? (
              <>
                {verified?.customerId ? <span>{verified.customerId}</span> : null}
                <span>CRM record is authoritative from here</span>
              </>
            ) : (
              <>
                <span>•••{persona.phoneLast4}</span>
                <span>{persona.product}</span>
                {persona.dpd > 0 && <span>DPD {persona.dpd}</span>}
                {persona.overdue > 0 && <span>₹{persona.overdue.toLocaleString()} overdue</span>}
                <span>{persona.language}</span>
              </>
            )}
          </div>
        </div>
        {/* The persona never disappears — the tester still needs to know which
            character they are playing — it just stops impersonating the
            account once a real one is bound. */}
        <div className="shrink-0 text-right text-body-small text-text-subtlest">
          <div>
            You're playing <span className="font-medium text-text-subtle">{persona.name}</span>
          </div>
          <div className="mt-025 flex items-center justify-end gap-050">
            <Lozenge tone="neutral" className="capitalize">
              {persona.mood}
            </Lozenge>
            <span className="truncate">{scenarioTitle}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
