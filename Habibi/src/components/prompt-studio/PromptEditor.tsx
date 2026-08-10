import { useRef } from "react";
import { AlertTriangle, Sparkles } from "lucide-react";
import { usePromptTokenEstimate, type PromptLintFinding } from "@/api/prompt-studio";
import { KNOWN_VARIABLES, PRESETS, detectUndefinedVars, type PersonaPreset } from "@/data/prompt-studio-seed";

type Props = {
  value: string;
  onChange: (next: string) => void;
  onApplyPreset: (preset: PersonaPreset) => void;
  presets?: PersonaPreset[];
  lintFindings?: PromptLintFinding[];
  onClearLint?: () => void;
};

export function PromptEditor({
  value,
  onChange,
  onApplyPreset,
  presets = PRESETS,
  lintFindings = [],
  onClearLint,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const estimateQuery = usePromptTokenEstimate(value);
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
  const estimate = estimateQuery.data;
  const tokens = estimate?.tokens;
  const costUsd = estimate?.costUsd;
  const accurate = estimate?.source === "tiktoken";

  return (
    <div className="grid gap-200 lg:grid-cols-[1fr_240px]">
      <div className="flex min-w-0 flex-col gap-100">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => {
            onChange(e.target.value);
            onClearLint?.();
          }}
          spellCheck={false}
          className="min-h-[22.5rem] w-full resize-y rounded-medium border border-border bg-surface p-150 font-mono text-body-small leading-relaxed text-text focus:outline-none focus:ring-2 focus:ring-border-brand/30"
        />
        <div className="flex flex-wrap items-center justify-between gap-100 text-body-small text-text-subtlest">
          <div>
            {value.length.toLocaleString()} chars ·{" "}
            {tokens == null ? (
              <span>counting tokens…</span>
            ) : accurate ? (
              <span>
                {tokens.toLocaleString()} tokens
                <span className="ml-050 text-text-subtlest/80">({estimate?.encoding})</span>
              </span>
            ) : (
              <span>≈{tokens.toLocaleString()} tokens (est.)</span>
            )}
          </div>
          <div title="Prompt-input only — excludes completion + RAG context">
            {costUsd == null
              ? "—"
              : accurate
                ? `Input cost/call: $${costUsd.toFixed(4)}`
                : `Est. cost/call: $${costUsd.toFixed(4)}`}
          </div>
        </div>
        {lintFindings.length > 0 && (
          <div className="space-y-050 rounded-medium border border-border-accent-gray-subtle bg-background-accent-gray-subtlest p-100">
            <div className="flex items-center justify-between text-body-small font-semibold text-text-subtlest">
              <span>Lint findings</span>
              {onClearLint && (
                <button type="button" onClick={onClearLint} className="normal-case tracking-normal hover:underline">
                  Clear
                </button>
              )}
            </div>
            {lintFindings.map((f, i) => (
              <div
                key={`${f.code}-${i}`}
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
              </div>
            ))}
          </div>
        )}
        {undefinedVars.length > 0 && (
          <div className="flex items-start gap-100 rounded-medium border border-border-warning-subtle bg-background-warning-subtler p-100 text-body-small text-text-warning-bolder">
            <AlertTriangle className="mt-025 h-3.5 w-3.5 shrink-0" />
            <div>
              Unknown variable(s): {undefinedVars.map((v) => (
                <code key={v} className="mx-025 rounded bg-surface/60 px-050 py-025 text-body-small">{`{${v}}`}</code>
              ))}
              {" "}— they won&apos;t be substituted at runtime.
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-200">
        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Variables</div>
          <div className="flex flex-wrap gap-050">
            {KNOWN_VARIABLES.map((v) => (
              <button
                key={v}
                onClick={() => insertVar(v)}
                className="rounded border border-border bg-surface-sunken px-075 py-025 font-mono text-body-small text-text-subtle hover:border-border-brand hover:text-text-brand"
              >
                {`{${v}}`}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-075 flex items-center gap-050 text-body-small font-semibold text-text-subtlest">
            <Sparkles className="h-3 w-3" /> Presets
          </div>
          <div className="flex flex-col gap-075">
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
