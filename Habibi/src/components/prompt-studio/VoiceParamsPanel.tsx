import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Info, Plus } from "lucide-react";

import type { ProviderModel } from "@/api/providers";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { ScrubField, SegmentedControl } from "./ScrubField";

/** One control descriptor, as declared by provider_models.params_schema. */
export type ParamSpec = {
  key: string;
  label: string;
  kind: "number" | "enum" | "bool" | "tag_palette";
  min?: number;
  max?: number;
  step?: number;
  default?: unknown;
  options?: string[];
  groups?: Record<string, string[]>;
  syntax?: string;
  maxPerSentence?: number;
  max_per_sentence?: number;
  transport?: string;
  help?: string;
};

/** Human labels for the tag groups, so the palette reads as sections. */
const GROUP_LABEL: Record<string, string> = {
  emotion: "Emotion",
  advanced: "Advanced emotion",
  tone: "Tone",
  effect: "Vocal effect",
  scene: "Scene & timing",
};

/** Markers a collections line should think twice about. Mirrors
 *  agent_core.providers.fish_emotions.RESTRICTED_ON_COLLECTIONS — warned, not
 *  blocked: whether an agent may shout at a debtor is a guardrail decision. */
const RESTRICTED = new Set([
  "angry",
  "shouting",
  "screaming",
  "contemptuous",
  "disdainful",
  "disgusted",
  "hysterical",
  "in a hurry tone",
]);

function decimalsFor(step?: number): number {
  if (!step || Number.isInteger(step)) return 0;
  return String(step).split(".")[1]?.length ?? 2;
}

const HELP_PREF_KEY = "voice-params-help";

/** Default off: the controls are labelled, and permanent prose under every one
 *  of them is what made this panel taller than the pane it lives in. */
function readHelpPref(): boolean {
  try {
    return window.localStorage.getItem(HELP_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Renders whatever controls the selected voice's model actually declares.
 *
 * The panel used to be Azure's knobs — rate, pitch, warmth, sentence pause —
 * shown for every voice, because Azure was the only provider. Those are the
 * controls of a *parametric* synthesiser and are not a superset of anything:
 * Fish S2.1 Pro has no pitch at all, and Deepgram Aura-2 has no prosody
 * whatsoever. Showing them anyway gives an operator sliders that move and
 * change nothing, which is the failure this codebase keeps finding in itself.
 *
 * So the schema comes from the row and the UI is generic over it. A provider
 * with an empty schema renders an explicit "no controls" note rather than
 * borrowing someone else's.
 */
export function VoiceParamsPanel({
  model,
  values,
  onChange,
  onInsertTag,
  disabled,
  modelsLoading,
}: {
  model: ProviderModel | null;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  /** Tag palettes write into the sample text, not into a value. */
  onInsertTag?: (tag: string) => void;
  disabled?: boolean;
  /** The provider-model list is still in flight, so `model` being null is not
   *  an answer yet. */
  modelsLoading?: boolean;
}) {
  // Memoised on the model, not on the `?? []` expression: a fresh empty array
  // each render would invalidate both memos below on every render, which is
  // exactly what they exist to avoid.
  const specs = useMemo(() => (model?.paramsSchema ?? []) as ParamSpec[], [model]);
  const scalar = useMemo(() => specs.filter((s) => s.kind !== "tag_palette"), [specs]);
  const palettes = useMemo(() => specs.filter((s) => s.kind === "tag_palette"), [specs]);
  const hasHelp = useMemo(() => specs.some((s) => Boolean(s.help)), [specs]);
  const [showHelp, setShowHelp] = useState(readHelpPref);

  // Persisted because it is a working preference, not a per-visit one: someone
  // learning the panel wants them on for a week, someone who knows it wants
  // them off forever. Re-asking every mount would serve neither.
  useEffect(() => {
    try {
      window.localStorage.setItem(HELP_PREF_KEY, showHelp ? "1" : "0");
    } catch {
      /* private mode — the toggle still works, it just won't persist */
    }
  }, [showHelp]);

  if (!model) {
    // Two different nulls. On a cold load the provider-model list has simply
    // not arrived yet, and a voice *is* selected — telling the operator to
    // select one is instructing them to redo something they already did.
    return (
      <p className="text-body-small text-text-subtlest">
        {modelsLoading
          ? "Loading this voice's controls…"
          : "Select a voice to see the controls its model supports."}
      </p>
    );
  }

  if (!specs.length) {
    return (
      <div className="flex flex-col gap-100">
        <RuntimeNotice model={model} />
        <div className="rounded-medium border border-border bg-surface-sunken px-150 py-100">
          <p className="text-body-small text-text-subtle">
            <span className="font-medium text-text">{model.displayName}</span> exposes no tunable
            controls through its API.
          </p>
          <p className="mt-050 text-body-small text-text-subtlest">
            Nothing is shown rather than borrowing another provider&rsquo;s sliders — a control that
            cannot be sent would do nothing.
          </p>
        </div>
      </div>
    );
  }

  return (
    // `@container` is the whole fix for this panel. Every breakpoint here used
    // to be a viewport one (`sm:`), which asks "is the window ≥640px?" — always
    // true — while the panel itself is a nested track roughly 400px wide. So it
    // rendered two columns into 400px and the ~190px cells clipped their labels
    // mid-word and overflowed onto each other. A container query asks the box.
    <div className="@container flex flex-col gap-150">
      <RuntimeNotice model={model} />
      <PersistenceNotice model={model} />

      <div className="flex items-center justify-between gap-100">
        <span className="text-body-small font-semibold text-text-subtlest">
          {model.displayName} controls
        </span>
        {/* Descriptions are off by default. Every control carried a permanent
            2–4 line explainer, which in a narrow pane tripled the panel's
            height and was the actual reason it needed to scroll at all. They
            stay one click away, and the choice is remembered. */}
        {hasHelp ? (
          <button
            type="button"
            onClick={() => setShowHelp((v) => !v)}
            aria-pressed={showHelp}
            className={cn(
              "inline-flex shrink-0 items-center gap-050 rounded-full border px-100 py-025",
              "text-body-tiny font-medium transition-colors",
              showHelp
                ? "border-border-brand bg-background-brand-subtlest text-text-brand"
                : "border-border text-text-subtlest hover:border-border-brand hover:text-text-brand",
            )}
          >
            <Info aria-hidden className="size-3" />
            {showHelp ? "Hide help" : "Help"}
          </button>
        ) : null}
      </div>

      <div className="grid gap-100 @md:grid-cols-2 @3xl:grid-cols-3">
        {scalar.map((spec) => {
          const value = values[spec.key] ?? spec.default;
          const changed = spec.default !== undefined && value !== spec.default;

          if (spec.kind === "number") {
            return (
              <div key={spec.key} className="flex flex-col gap-050">
                <ScrubField
                  label={spec.label}
                  value={Number(value ?? 0)}
                  onChange={(v) => onChange(spec.key, v)}
                  // `?? 0` is wrong for any schema that omits `min` and
                  // allows negatives — Fish's volume is -20..20, Azure's pitch
                  // is +/-50. Every seeded schema declares both today, so this
                  // is latent; the fallbacks are widened rather than left as a
                  // silent floor at zero for the first one that does not.
                  min={spec.min ?? Number.NEGATIVE_INFINITY}
                  max={spec.max ?? Number.POSITIVE_INFINITY}
                  step={spec.step ?? 1}
                  precision={decimalsFor(spec.step)}
                  active={changed}
                  disabled={disabled}
                />
                {showHelp && spec.help ? (
                  <span className="px-050 text-body-tiny leading-snug text-text-subtlest">
                    {spec.help}
                  </span>
                ) : null}
              </div>
            );
          }

          if (spec.kind === "enum") {
            const options = spec.options ?? [];
            // A stored value that has left the schema is shown, not hidden.
            //
            // The control fell back to `options[0]` whenever the stored value
            // was not one it offers — but `effectiveParams` still SENDS the
            // stored value, so the panel displayed one setting while the wire
            // carried another. The author reads "normal", the synthesiser is
            // asked for a mode that no longer exists, and the only sign
            // anything is wrong is the output.
            const stored = value == null ? "" : String(value);
            const orphaned = stored !== "" && !options.includes(stored);
            return (
              <div key={spec.key} className="flex min-w-0 flex-col gap-050">
                <span
                  title={spec.label}
                  className="truncate px-050 text-body-tiny font-medium tracking-wide text-text-subtlest uppercase"
                >
                  {spec.label}
                </span>
                <SegmentedControl
                  ariaLabel={spec.label}
                  value={orphaned ? stored : String(value ?? options[0] ?? "")}
                  onChange={(v) => onChange(spec.key, v)}
                  options={(orphaned ? [...options, stored] : options).map((o) => ({
                    value: o,
                    label: o === stored && orphaned ? `${o} (not offered)` : o,
                  }))}
                />
                {orphaned ? (
                  <span className="px-050 text-body-tiny leading-snug text-text-warning-bolder">
                    <span className="font-mono">{stored}</span> is stored on this version but this
                    voice no longer offers it. It is still what gets sent — pick another to replace
                    it.
                  </span>
                ) : null}
                {showHelp && spec.help ? (
                  <span className="px-050 text-body-tiny leading-snug text-text-subtlest">
                    {spec.help}
                  </span>
                ) : null}
              </div>
            );
          }

          // bool
          return (
            <label
              key={spec.key}
              className="flex items-start gap-100 rounded-md bg-surface-sunken px-100 py-075"
            >
              <Switch
                aria-label={spec.label}
                checked={Boolean(value)}
                disabled={disabled}
                onCheckedChange={(v) => onChange(spec.key, v)}
              />
              <span className="min-w-0">
                <span className="block text-body-small font-medium text-text">{spec.label}</span>
                {showHelp && spec.help ? (
                  <span className="block text-body-tiny leading-snug text-text-subtlest">
                    {spec.help}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>

      {palettes.map((spec) => (
        <TagPalette
          key={spec.key}
          spec={spec}
          disabled={disabled}
          onInsert={(tag) => onInsertTag?.(tag)}
        />
      ))}
    </div>
  );
}

/**
 * Which of these controls the editor can actually keep.
 *
 * Azure's four map onto `VoiceConfig` columns the version already stores, so
 * they autosave and publish. Every other provider's controls are held in the
 * panel's own state: they change what you hear here and nothing further — not
 * saved, not published, gone on a tab switch, because `AgentTuning.tts` is a
 * closed Azure-shaped set with nowhere to put them.
 *
 * Said plainly and once, at the top. A slider that moves, audibly changes the
 * preview, and then silently does not ship is worse than one that is disabled:
 * the disabled one tells you.
 */
/**
 * What happens to these values after you leave the screen.
 *
 * This used to say "preview only", and it was true: the controls lived in
 * VoicePanel's state, so nothing outside Azure's four reached a call. They are
 * on `VoiceConfig.params` now and fold into `AgentTuning.tts.params` at save,
 * so the honest note is the opposite one — and it still has a caveat worth
 * printing, because the provider's `Settings` class is what decides which keys
 * survive construction, not this panel.
 */
function PersistenceNotice({ model }: { model: ProviderModel }) {
  const speaks = model.runtime === "live";
  return (
    <div className="flex items-start gap-100 rounded-medium border border-border-information-subtle bg-background-information-subtler px-150 py-100">
      <Info aria-hidden className="mt-025 size-3.5 shrink-0 text-text-information-bolder" />
      <div className="min-w-0">
        <p className="text-body-small font-medium text-text-information-bolder">
          {speaks
            ? "These settings publish with the version"
            : "These settings save, but this model cannot take a call"}
        </p>
        <p className="mt-025 text-body-tiny leading-snug text-text-subtle">
          {speaks ? (
            <>
              They are saved on the version and folded into the deployment&rsquo;s tuning, so a
              published call is synthesized with what you hear here. A control this provider stops
              accepting is dropped when the call is built rather than failing it.
            </>
          ) : (
            <>
              They are saved on the version, but a call bound to this model falls back to Azure —
              see the note above. Auditioning is real; the call is not this voice.
            </>
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * Whether this voice can run on a call, when the answer is not "yes".
 *
 * Auditioning and calling are different capabilities and they fail for
 * different reasons: a model can have a key, list voices, and preview
 * perfectly while having no streaming integration behind it — or naming a
 * service class that does not import. Both used to bind exactly like a working
 * model and fall back to Azure on the call, so the operator heard a voice they
 * had not chosen with nothing on screen to explain it.
 *
 * Nothing renders in the healthy case; a badge that says "fine" on every row
 * trains people to stop reading it.
 */
function RuntimeNotice({ model }: { model: ProviderModel }) {
  if (model.runtime === "live") return null;

  const preview = model.runtime === "preview_only";
  return (
    <div
      className={cn(
        "flex items-start gap-100 rounded-medium border px-150 py-100",
        preview
          ? "border-border-warning-subtle bg-background-warning-subtler"
          : "border-border-danger-subtle bg-background-danger-subtler",
      )}
    >
      <Info
        aria-hidden
        className={cn(
          "mt-025 size-3.5 shrink-0",
          preview ? "text-text-warning-bolder" : "text-text-danger-bolder",
        )}
      />
      <div className="min-w-0">
        <p
          className={cn(
            "text-body-small font-medium",
            preview ? "text-text-warning-bolder" : "text-text-danger-bolder",
          )}
        >
          {preview ? "Audition only — will not run on a call" : "Cannot run on a call"}
        </p>
        <p className="mt-025 text-body-tiny leading-snug text-text-subtle">
          {preview
            ? "You can preview this voice here, but it has no streaming integration, so binding it would fall back to the default provider mid-call."
            : model.runtimeDetail || "The service for this model is not installed."}
        </p>
      </div>
    </div>
  );
}

/**
 * Emotion / effect markers, inserted into the sample text.
 *
 * Not a dropdown, because the vendor does not have a fixed list: Fish accepts
 * free-form descriptions inside brackets, so a closed picker would cap the
 * model well below what it can do. The palette is a shortcut for the common
 * ~70; the free-text box is the actual interface.
 */
function TagPalette({
  spec,
  onInsert,
  disabled,
}: {
  spec: ParamSpec;
  onInsert: (tag: string) => void;
  disabled?: boolean;
}) {
  const groups = spec.groups ?? {};
  const groupKeys = Object.keys(groups);
  const [group, setGroup] = useState(groupKeys[0] ?? "");
  const [custom, setCustom] = useState("");
  const [open, setOpen] = useState(false);
  const maxPer = spec.maxPerSentence ?? spec.max_per_sentence ?? 3;
  const syntax = spec.syntax ?? "[tag]";
  const total = groupKeys.reduce((n, g) => n + (groups[g]?.length ?? 0), 0);

  if (!groupKeys.length) return null;

  return (
    // Collapsed by default. ~70 chips across five groups plus a free-text box
    // is the single tallest block in the inspector, and it is used on a
    // minority of turns — it earns its space on demand, not by default.
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-medium border border-border bg-surface-sunken"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-100 px-150 py-100 text-left">
        <ChevronDown
          aria-hidden
          className={cn(
            "size-3.5 shrink-0 text-text-subtlest transition-transform duration-200",
            open && "rotate-180",
          )}
        />
        <span className="min-w-0 flex-1 truncate text-body-small font-medium text-text">
          {spec.label}
        </span>
        <span className="shrink-0 text-body-tiny text-text-subtlest tabular-nums">{total}</span>
      </CollapsibleTrigger>

      <CollapsibleContent className="flex flex-col gap-100 px-150 pb-150">
        <span className="block text-body-tiny leading-snug text-text-subtlest">
          Inserted as <code className="font-mono">{syntax}</code> at the cursor. Placement is
          meaning — a marker applies from where it sits onward. Max {maxPer} per sentence; markers
          are never spoken.
        </span>

        <div className="flex flex-wrap gap-050">
          {groupKeys.map((g) => (
            <button
              key={g}
              type="button"
              aria-pressed={g === group}
              onClick={() => setGroup(g)}
              className={cn(
                "rounded-full px-150 py-025 text-body-tiny font-medium transition-colors",
                g === group
                  ? "bg-surface text-text shadow-raised"
                  : "text-text-subtle hover:bg-surface-hovered",
              )}
            >
              {GROUP_LABEL[g] ?? g}
              <span className="ml-075 text-body-micro text-text-subtlest tabular-nums">
                {groups[g]?.length ?? 0}
              </span>
            </button>
          ))}
        </div>

        <div className="flex max-h-[8.5rem] flex-wrap gap-050 overflow-y-auto">
          {(groups[group] ?? []).map((tag) => {
            const restricted = RESTRICTED.has(tag);
            return (
              <button
                key={tag}
                type="button"
                disabled={disabled}
                onClick={() => onInsert(tag)}
                title={
                  restricted
                    ? "Aggressive delivery — review against your compliance guardrails before using on a collections line"
                    : `Insert [${tag}]`
                }
                className={cn(
                  "inline-flex items-center gap-050 rounded-medium border px-100 py-025",
                  "text-body-tiny transition-colors disabled:opacity-50",
                  restricted
                    ? "border-border-warning-subtle bg-background-warning-subtler text-text-warning-bolder hover:border-border-warning"
                    : "border-border bg-surface text-text-subtle hover:border-border-brand hover:text-text-brand",
                )}
              >
                <Plus aria-hidden className="size-2.5" />
                {tag}
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-075">
          <input
            value={custom}
            disabled={disabled}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && custom.trim()) {
                e.preventDefault();
                onInsert(custom.trim());
                setCustom("");
              }
            }}
            placeholder="…or describe it: laughing nervously"
            className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface px-100 text-body-small text-text outline-none focus:border-border-brand"
          />
          <button
            type="button"
            disabled={disabled || !custom.trim()}
            onClick={() => {
              onInsert(custom.trim());
              setCustom("");
            }}
            className="h-8 shrink-0 rounded-md border border-border bg-surface px-150 text-body-small font-medium text-text-subtle hover:border-border-brand hover:text-text-brand disabled:opacity-50"
          >
            Insert
          </button>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
