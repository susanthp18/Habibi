import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Sparkles, X } from "lucide-react";
import { usePromptTokenEstimate, type PromptLintFinding } from "@/api/prompt-studio";
import {
  SYSTEM_SAFE_VARIABLES,
  detectCrmVars,
  detectFlowVars,
  detectUndefinedVars,
  type Guardrails,
  type PersonaPreset,
  type PersonaState,
} from "@/data/prompt-studio-seed";

type Props = {
  value: string;
  onChange: (next: string) => void;
  onApplyPreset: (preset: PersonaPreset) => void;
  presets?: PersonaPreset[];
  lintFindings?: PromptLintFinding[];
  onClearLint?: () => void;
  /** Scopes the dismissed-suggestion list. One card's dismissals must not
   *  silence another's — the advice is about this prompt, not the tenant. */
  botId?: string;
  /** Sent with the token estimate so the figure describes the assembled call. */
  guardrails?: Guardrails;
  persona?: PersonaState;
};

export function PromptEditor({
  value,
  onChange,
  onApplyPreset,
  presets = [],
  lintFindings = [],
  onClearLint,
  guardrails,
  persona,
  botId,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const estimateQuery = usePromptTokenEstimate({
    prompt: value,
    guardrails,
    persona,
    channel: "voice",
  });
  const insertVar = (name: string) => {
    const el = ref.current;
    const token = `{${name}}`;
    if (!el) return onChange(value + token);
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const next = value.slice(0, start) + token + value.slice(end);
    onChange(next);
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + token.length;
    });
  };

  const undefinedVars = detectUndefinedVars(value);
  const crmVars = detectCrmVars(value);
  const flowVars = detectFlowVars(value);
  // The CRM and flow-syntax banners below are always on and each states its
  // consequence once, for every token it found. The backend reports the same
  // thing as one verbose finding per token, so a four-token prompt rendered the
  // identical warning five times and pushed everything else off screen. Show
  // each finding in exactly one place.
  // The AI review's suggestions render as their own checklist below, so they
  // are excluded here for the same reason the CRM and flow findings are: a
  // finding shown in two places reads as two findings.
  const INLINE_CODES = new Set([
    "crm_variable_in_system_prompt",
    "flow_syntax_in_prompt",
    "llm_checklist",
  ]);
  // Collapsed by (code, message), which is the invariant the comment above
  // claims and the code did not have. The backend reports positional findings
  // once per HIT — `unknown_variable` carries the variable's own name in its
  // message, so a prompt using `{foo}` three times printed three identical
  // rows, while `{foo}` and `{bar}` stay correctly distinct. The dedupe used to
  // exist only as a hardcoded exclusion list for the two codes someone had
  // already been bitten by; anything added to the linter later inherited the
  // bug by default.
  const otherFindings = (() => {
    const seen = new Map<string, { finding: PromptLintFinding; count: number }>();
    for (const f of lintFindings) {
      if (INLINE_CODES.has(f.code)) continue;
      const key = `${f.code} :: ${f.message}`;
      const hit = seen.get(key);
      if (hit) hit.count += 1;
      else seen.set(key, { finding: f, count: 1 });
    }
    return [...seen.values()];
  })();

  // Advisory only. These are a model's opinion about a prompt, so they are
  // never applied automatically — dismissing one is the only write.
  const aiFindings = lintFindings.filter((f) => f.code === "llm_checklist");
  const dismissKey = `prompt-studio:ai-review-dismissed:${botId ?? "unknown"}`;
  const [dismissed, setDismissed] = useState<string[]>([]);
  useEffect(() => {
    // Read in an effect rather than a useState initialiser: the key depends on
    // botId, and switching cards has to re-read rather than keep the first
    // card's list. A malformed or unreadable entry degrades to "nothing
    // dismissed", which shows too much rather than hiding something.
    try {
      const raw = window.localStorage.getItem(dismissKey);
      const parsed: unknown = raw ? JSON.parse(raw) : [];
      setDismissed(
        Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [],
      );
    } catch {
      setDismissed([]);
    }
  }, [dismissKey]);

  const dismiss = (message: string) => {
    const next = [...new Set([...dismissed, message])];
    setDismissed(next);
    try {
      window.localStorage.setItem(dismissKey, JSON.stringify(next));
    } catch {
      // Private mode / quota. The suggestion still disappears for this session.
    }
  };

  const openAdvice = aiFindings.filter((f) => !dismissed.includes(f.message));
  const estimate = estimateQuery.data;
  // True while the number belongs to an earlier revision of the text — the
  // query keeps the previous result as placeholder data so the figure does not
  // flicker, which also means it silently describes a prompt you have already
  // changed.
  const lagging = estimateQuery.isPlaceholderData;
  const tokens = estimate?.tokens;
  const accurate = estimate?.source === "tiktoken";
  // The figure that bills. The footer used to show the authored count and its
  // cost alone, which on a real card understates the system message by about
  // 8x — the guardrail rules, persona directions, local time and the voice
  // naturalness overlay are all generated at call time and are most of the
  // message. Null only when the caller sent no guardrails to assemble with.
  const shipped = estimate?.assembledTokens ?? null;
  const shippedCostUsd = estimate?.assembledCostUsd ?? null;

  return (
    <div className="grid gap-200 lg:grid-cols-[1fr_240px]">
      <div className="flex min-w-0 flex-col gap-100">
        <textarea
          ref={ref}
          value={value}
          // No longer discards the findings on every keystroke: the Studio hides
          // them whenever the prompt or the guardrails differ from what was
          // linted, so typing and undoing brings the real result back instead of
          // leaving an empty panel that looks like a clean bill of health.
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="min-h-[22.5rem] w-full resize-y rounded-medium border border-border bg-surface p-150 font-mono text-body-small leading-relaxed text-text focus:outline-none focus:ring-2 focus:ring-border-brand/30"
        />
        <div
          className={`flex flex-wrap items-center justify-between gap-100 text-body-small text-text-subtlest ${
            lagging ? "opacity-60" : ""
          }`}
        >
          <div>
            {value.length.toLocaleString()} chars ·{" "}
            {tokens == null ? (
              <span>counting tokens…</span>
            ) : (
              <span title="The text in this editor, before the runtime adds anything.">
                {accurate ? "" : "≈"}
                {tokens.toLocaleString()} authored
                {accurate && (
                  <span className="ml-050 text-text-subtlest/80">({estimate?.encoding})</span>
                )}
              </span>
            )}
          </div>
          {/* Two figures, because they answer different questions and the gap
              between them is the point. "Authored" is what you can edit;
              "sent" is what the model reads and what the invoice reflects. */}
          <div className="flex items-center gap-100">
            {shipped != null && tokens != null && (
              <span
                title={
                  "The assembled system message: your text plus the guardrail rules, persona " +
                  "directions, local time and voice conversation rules the runtime generates. " +
                  "Re-sent on every LLM call — 2-3x per turn."
                }
              >
                <strong className="font-semibold text-text-subtle">
                  {shipped.toLocaleString()} sent/call
                </strong>
                {tokens > 0 && (
                  <span className="ml-050 text-text-subtlest/80">
                    ({Math.round((shipped / tokens) * 10) / 10}×)
                  </span>
                )}
              </span>
            )}
            <span title="Prompt-input only — excludes completion + RAG context.">
              {shippedCostUsd != null
                ? `$${shippedCostUsd.toFixed(4)}/call`
                : estimate?.costUsd == null
                  ? "—"
                  : `$${estimate.costUsd.toFixed(4)}/call (authored only)`}
            </span>
          </div>
        </div>
        {otherFindings.length > 0 && (
          <div className="space-y-050 rounded-medium border border-border-accent-gray-subtle bg-background-accent-gray-subtlest p-100">
            <div className="flex items-center justify-between text-body-small font-semibold text-text-subtlest">
              <span>Lint findings</span>
              {onClearLint && (
                <button
                  type="button"
                  onClick={onClearLint}
                  className="normal-case tracking-normal hover:underline"
                >
                  Clear
                </button>
              )}
            </div>
            {otherFindings.map(({ finding: f, count }) => (
              <div
                key={`${f.code}-${f.message}`}
                className={`rounded px-100 py-050 text-body-small ${
                  f.severity === "error"
                    ? "bg-background-danger-subtler text-text-danger-bolder"
                    : f.severity === "warn"
                      ? "bg-background-warning-subtler text-text-warning-bolder"
                      : "bg-surface text-text-subtle"
                }`}
              >
                <span className="mr-050 font-mono text-body-small opacity-70">{f.severity}</span>
                {f.message}
                {count > 1 && <span className="ml-050 opacity-70">({count} occurrences)</span>}
              </div>
            ))}
          </div>
        )}
        {flowVars.length > 0 && (
          <div className="flex items-start gap-100 rounded-medium border border-border-danger bg-background-danger-subtler p-100 text-body-small text-text-danger-bolder">
            <AlertTriangle className="mt-025 h-3.5 w-3.5 shrink-0" />
            <div>
              Flow syntax in a prompt:{" "}
              {flowVars.map((v) => (
                <code
                  key={v}
                  className="mx-025 rounded bg-surface/60 px-050 py-025 text-body-small"
                >{`{{ ${v} }}`}</code>
              ))}{" "}
              — double braces are the <strong>Flow</strong> tab&apos;s syntax. A prompt never
              substitutes them and never strips them, so the braces are <strong>read aloud</strong>.
              Use a single brace here, and only for the operator variables listed on the right.
            </div>
          </div>
        )}
        {crmVars.length > 0 && (
          <div className="flex items-start gap-100 rounded-medium border border-border-warning-subtle bg-background-warning-subtler p-100 text-body-small text-text-warning-bolder">
            <AlertTriangle className="mt-025 h-3.5 w-3.5 shrink-0" />
            <div>
              CRM field(s) in a system prompt:{" "}
              {crmVars.map((v) => (
                <code
                  key={v}
                  className="mx-025 rounded bg-surface/60 px-050 py-025 text-body-small"
                >{`{${v}}`}</code>
              ))}{" "}
              — a system prompt only substitutes operator variables, so the runtime drops{" "}
              <strong>the whole line</strong> each of these sits on. The real values reach the model
              on the untrusted CRM context card; refer to them in words (&ldquo;the caller&apos;s
              account&rdquo;) instead.
            </div>
          </div>
        )}
        {undefinedVars.length > 0 && (
          <div className="flex items-start gap-100 rounded-medium border border-border-warning-subtle bg-background-warning-subtler p-100 text-body-small text-text-warning-bolder">
            <AlertTriangle className="mt-025 h-3.5 w-3.5 shrink-0" />
            <div>
              Unknown variable(s):{" "}
              {undefinedVars.map((v) => (
                <code
                  key={v}
                  className="mx-025 rounded bg-surface/60 px-050 py-025 text-body-small"
                >{`{${v}}`}</code>
              ))}{" "}
              — they won&apos;t be substituted at runtime.
            </div>
          </div>
        )}
        {/* Advisory rows, under the editor rather than in the 240px rail.
            They used to sit beside the Presets, which was survivable while the
            model was answering in fragments ("escalateAbuse: Not explicitly
            required."). Now that it critiques the writing it answers in whole
            sentences, and five of those in a 240px column ran to ~600px of
            rail — the grid stretches both columns to the taller one, so the
            editor side rendered a screenful of blank white beneath the
            textarea. Prose belongs in the wide column, next to the text it is
            about. */}
        {openAdvice.length > 0 ? (
          <div>
            <div className="mb-075 flex items-center gap-050 text-body-small font-semibold text-text-subtlest">
              <Sparkles className="h-3 w-3" /> Critique wording
            </div>
            <ul className="flex flex-col gap-075">
              {openAdvice.map((f) => (
                <li
                  key={f.message}
                  className="flex items-start gap-075 rounded-medium border border-border bg-surface px-100 py-075 text-body-small"
                >
                  <span className="flex-1 text-text-subtle">{f.message}</span>
                  <button
                    type="button"
                    onClick={() => dismiss(f.message)}
                    title="Dismiss — advisory only, nothing is applied"
                    aria-label="Dismiss suggestion"
                    className="mt-025 text-text-subtlest hover:text-text"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-200">
        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Variables</div>
          <div className="flex flex-wrap gap-050">
            {SYSTEM_SAFE_VARIABLES.map((v) => (
              <button
                key={v}
                onClick={() => insertVar(v)}
                title="Substituted at call start"
                className="rounded border border-border bg-surface-sunken px-075 py-025 font-mono text-body-small text-text-subtle hover:border-border-brand hover:text-text-brand"
              >
                {`{${v}}`}
              </button>
            ))}
          </div>
          {/* The CRM fields are deliberately not offered.
              Nothing substitutes them here: every runtime renders this prompt
              with render_system_prompt (operator tokens only) and then deletes
              any line still holding a CRM token. The only caller of the
              full-substitution renderer is a sandbox opening-message template,
              which is not authored on this tab. Offering a button that silently
              deletes the line you put it on is not a palette, it is a trap —
              listing them behind a warning was the same trap with a label. */}
          <p className="mt-100 text-body-small leading-relaxed text-text-subtlest">
            Customer details — name, account, amounts, dates — are not variables here. The runtime
            attaches them as a separate CRM context card that is refreshed as the call learns who it
            is talking to. Refer to them in words: &ldquo;the caller&apos;s account&rdquo;,
            &ldquo;the amount shown in the CRM card&rdquo;.
          </p>
          {/* Said once, here, because the two syntaxes are two tabs apart and
              look alike. Authors reached for the Flow spelling in a prompt and
              got braces spoken aloud; the banner below the editor catches it
              after the fact, this is what stops it being written. */}
          <p className="mt-100 rounded-medium border border-border bg-surface-sunken p-100 text-body-small leading-relaxed text-text-subtlest">
            <span className="font-medium text-text-subtle">Not the Flow tab&apos;s syntax.</span>{" "}
            Here <code className="font-mono">{"{single}"}</code> braces substitute the four
            variables above and nothing else. In <strong>Flow</strong>, a step uses{" "}
            <code className="font-mono">{"{{ double }}"}</code> braces and those do reach customer
            data. Double braces typed here are never substituted and never removed — they are
            spoken.
          </p>
        </div>
        <div>
          <div className="mb-075 flex items-center gap-050 text-body-small font-semibold text-text-subtlest">
            <Sparkles className="h-3 w-3" /> Presets
          </div>
          <div className="flex flex-col gap-075">
            {presets.length === 0 ? (
              <p className="text-body-small text-text-subtle">
                No presets configured. They are seeded per tenant in{" "}
                <span className="font-mono">persona_presets</span>.
              </p>
            ) : null}
            {presets.map((p) => (
              <button
                key={p.id}
                onClick={() => onApplyPreset(p)}
                className="rounded-medium border border-border bg-surface px-100 py-075 text-left text-body-small hover:border-border-brand"
              >
                <div className="font-medium text-text">{p.label}</div>
                <div className="text-body-small text-text-subtlest">{p.description}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
