import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  diffStudioVersions,
  type Guardrails,
  type PersonaState,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import type { CompileReport } from "@/api/agent-studio";
import { CompileReportList } from "@/components/prompt-studio/AgentCardPanels";
import type { FlowGraph, FlowIssue } from "@/api/flow";
import type { AgentCard } from "@/api/agent-card";
import { cn } from "@/lib/utils";
import { stableStringify } from "@/lib/stable-stringify";

type DiffSide = {
  prompt: string;
  persona: PersonaState;
  voice: VoiceConfig;
  guardrails: Guardrails;
  /** Publish sends these two as well; see `changedSections` below. */
  flow?: FlowGraph | null;
  agentCard?: AgentCard | null;
  /**
   * Rollout, for bots that have nowhere else to keep it.
   *
   * An authored card carries traffic/shadow/auto-rollback under
   * `agentCard.experiment`, so `cardChanged` already covers it. A card-less bot
   * keeps the same three values in editor-local state, and publish ships them —
   * so moving the canary to 40% and enabling shadow used to be summarised as
   * "Nothing differs from what is live", on the one screen whose job is to say
   * what is about to change about production.
   */
  rollout?: { trafficPct: number; shadow: boolean; autoRollback: string[] } | null;
};

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fromLabel: string;
  toLabel: string;
  from: DiffSide;
  to: DiffSide;
  onConfirm: (note: string) => void;
  flowIssues?: FlowIssue[];
  compileReport?: CompileReport | null;
  /** Set when the compile call itself failed, so no report exists to show. */
  compileError?: string | null;
  compileBusy?: boolean;
};

export function PublishDialog({
  open,
  onOpenChange,
  fromLabel,
  toLabel,
  from,
  to,
  onConfirm,
  flowIssues = [],
  compileReport = null,
  compileError = null,
  compileBusy = false,
}: Props) {
  const [confirmText, setConfirmText] = useState("");
  const [localeConfirm, setLocaleConfirm] = useState("");
  const [note, setNote] = useState("");
  const lines = diffStudioVersions(from, to);
  const added = lines.filter((l) => l.kind === "add").length;
  const removed = lines.filter((l) => l.kind === "del").length;

  // Publish sends six things; the line diff covers four of them.
  //
  // It called itself "Full config diff" while `flow` and `agentCard` went out
  // untouched by it, so rewiring the conversation graph — or adding a tool,
  // binding a connector, moving the canary to 40% — was announced as
  // "+0 · −0 lines". The most consequential publishes were the ones the dialog
  // described as changing nothing.
  //
  // Reported as changed/unchanged rather than folded into the line count: a
  // graph and a card are structured JSON, and rendering them as added and
  // removed text lines produces a number that is technically derived from the
  // change and tells the reader nothing about it.
  const flowChanged = stableStringify(from.flow ?? null) !== stableStringify(to.flow ?? null);
  const cardChanged =
    stableStringify(from.agentCard ?? null) !== stableStringify(to.agentCard ?? null);
  const rolloutChanged =
    stableStringify(from.rollout ?? null) !== stableStringify(to.rollout ?? null);
  const nothingChanges =
    added === 0 && removed === 0 && !flowChanged && !cardChanged && !rolloutChanged;
  const errors = flowIssues.filter((i) => i.severity === "error");
  const compileFailed = (compileReport?.gates ?? []).some((g) => g.status === "fail");
  // Publish waits for the compiler.
  //
  // `compileReport` is the *previous* run until the new one lands, so opening
  // this dialog a second time showed the last card's gate list under a
  // "Running compiler…" banner, and `blocked` was decided by it: a run that
  // failed last time disabled Confirm for a config that now passes, and one
  // that passed left Confirm live while the real answer was still in flight.
  const blocked = errors.length > 0 || compileFailed || compileBusy;

  /**
   * A voice that speaks a language the card does not claim.
   *
   * G15 warns rather than fails, deliberately: a localisation override is a
   * real thing an operator does. But "PUBLISH" is already typed on every
   * publish, so a warning alone would be read past. A second word names *this*
   * decision, which is the difference between confirming a publish and
   * confirming a bot that answers in a language its card was not written for.
   */
  const localeWarning = (compileReport?.gates ?? []).find(
    (g) => g.gate === "G15" && g.status === "warn",
  );
  const localeIssue = localeWarning?.issues?.[0] as
    { voice?: string; voiceLocale?: string; cardLocales?: string[] } | undefined;
  // Both typed gates normalize identically. They did not: PUBLISH was matched
  // raw and case-sensitively while LANGUAGE was trimmed and uppercased, so a
  // trailing space — the thing a paste reliably adds — defeated one gate and
  // not the other, for no reason the author could see.
  const typed = (value: string) => value.trim().toUpperCase();
  const localeConfirmed = !localeWarning || typed(localeConfirm) === "LANGUAGE";
  const publishConfirmed = typed(confirmText) === "PUBLISH";

  /**
   * A confirmation gate is never pre-satisfied when it opens.
   *
   * The reset used to live in `onOpenChange`, which Radix calls only for closes
   * *it* initiates — Escape, the overlay, Cancel. A successful publish closes
   * this dialog programmatically (`setPublishOpen(false)`), so that path skipped
   * the reset entirely and the component stayed mounted holding
   * `confirmText === "PUBLISH"`, the typed LANGUAGE override, and the previous
   * change note. Opening it again in the same session presented a Confirm
   * button that was already enabled, on a publish nobody had typed anything to
   * confirm, filed under a note describing the *last* publish. That is the whole
   * gate defeated by the happy path.
   *
   * Resetting on open cannot be skipped by any close path, because it does not
   * depend on one.
   */
  useEffect(() => {
    if (!open) return;
    setConfirmText("");
    setLocaleConfirm("");
    setNote("");
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Publish <span className="font-mono">{toLabel}</span>?
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-150 text-body">
          {compileBusy && (
            <div className="rounded-medium border border-border bg-surface-sunken p-150 text-body-small text-text-subtle">
              Running compiler G0–G15…
            </div>
          )}
          {compileError && !compileBusy && (
            <div className="rounded-medium border border-border-warning bg-background-warning-subtler p-150 text-body-small text-text-warning-bolder">
              <div className="font-semibold">The compiler could not be reached</div>
              <p className="mt-025">
                {compileError} No gate evidence is available for this publish. The API re-runs every
                gate on Confirm and will reject the publish if any of them fails — but you are
                confirming without seeing them.
              </p>
            </div>
          )}
          {compileReport && !compileBusy && (
            <div className="rounded-medium border border-border p-150">
              <div className="mb-075 text-body-small font-semibold">Compiler report</div>
              <CompileReportList report={compileReport} />
            </div>
          )}
          {errors.length > 0 && (
            <div className="rounded-medium border border-border-danger bg-background-danger-subtler p-150 text-body-small text-text-danger-bolder">
              <div className="font-semibold">Flow compiler failed — cannot publish</div>
              <ul className="mt-050 list-disc space-y-025 pl-200">
                {errors.map((issue, i) => (
                  <li key={`${issue.code}-${i}`}>{issue.message}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="space-y-075 rounded-medium border border-border bg-surface-sunken p-150">
            <div className="text-text-subtle">
              {fromLabel === "nothing live" ? (
                "First publish — nothing is live yet. Text config: "
              ) : (
                <>
                  Replacing live <span className="font-mono">{fromLabel}</span>. Text config:{" "}
                </>
              )}
              <span className="font-medium text-text-success-bolder">+{added}</span> ·{" "}
              <span className="font-medium text-text-danger-bolder">−{removed}</span> lines (prompt
              + persona + voice + guardrails).
            </div>
            <div className="flex flex-wrap gap-x-200 gap-y-025 text-body-small text-text-subtle">
              <span>
                Flow graph:{" "}
                <span
                  className={cn(
                    "font-medium",
                    flowChanged ? "text-text-warning-bolder" : undefined,
                  )}
                >
                  {flowChanged ? "changed" : "unchanged"}
                </span>
              </span>
              <span>
                Rollout:{" "}
                <span
                  className={cn(
                    "font-medium",
                    rolloutChanged ? "text-text-warning-bolder" : undefined,
                  )}
                >
                  {rolloutChanged ? "changed" : "unchanged"}
                </span>
              </span>
              <span>
                Agent card:{" "}
                <span
                  className={cn(
                    "font-medium",
                    cardChanged ? "text-text-warning-bolder" : undefined,
                  )}
                >
                  {cardChanged ? "changed" : "unchanged"}
                </span>
              </span>
            </div>
            {nothingChanges ? (
              // Reachable: publish is enabled by an existing draft, not only by
              // a diff, so you can land here with nothing to ship. Saying so is
              // better than a row of zeroes the reader has to interpret.
              <div className="text-body-small text-text-subtlest">
                Nothing differs from what is live — this publishes an identical version.
              </div>
            ) : null}
          </div>
          <div>
            <label className="text-body-small font-semibold text-text-subtlest">Change note</label>
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What changed and why"
            />
          </div>
          {localeWarning && (
            <div className="space-y-075 rounded-medium border border-border-warning bg-background-warning-subtler p-150 text-body-small text-text-warning-bolder">
              <div className="font-semibold">
                Publish with a voice that does not match the card language?
              </div>
              <p>
                {localeIssue?.voiceLocale && localeIssue?.cardLocales?.length ? (
                  <>
                    <span className="font-mono">{localeIssue.voice}</span> speaks{" "}
                    <span className="font-mono">{localeIssue.voiceLocale}</span>; this card is
                    authored for{" "}
                    <span className="font-mono">{localeIssue.cardLocales.join(", ")}</span>.
                  </>
                ) : (
                  localeWarning.detail
                )}{" "}
                Callers hear the voice, not the card. If that is deliberate — a localisation
                override — say so.
              </p>
              <label className="block font-semibold">
                Type <span className="font-mono">LANGUAGE</span> to confirm
              </label>
              <Input
                value={localeConfirm}
                onChange={(e) => setLocaleConfirm(e.target.value)}
                placeholder="LANGUAGE"
              />
            </div>
          )}
          <div>
            <label className="text-body-small font-semibold text-text-subtlest">
              Type <span className="font-mono">PUBLISH</span> to confirm
            </label>
            <Input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="PUBLISH"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={blocked || !publishConfirmed || !localeConfirmed}
            onClick={() => onConfirm(note || `Published ${toLabel}`)}
          >
            Publish {toLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
