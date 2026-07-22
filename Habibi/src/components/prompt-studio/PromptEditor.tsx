import { useRef } from "react";
import { AlertTriangle, Sparkles } from "lucide-react";
import { KNOWN_VARIABLES, PRESETS, detectUndefinedVars, estimateTokens, type PersonaPreset } from "@/data/prompt-studio-seed";

type Props = {
  value: string;
  onChange: (next: string) => void;
  onApplyPreset: (preset: PersonaPreset) => void;
};

export function PromptEditor({ value, onChange, onApplyPreset }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
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
  const tokens = estimateTokens(value);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
      <div className="flex min-w-0 flex-col gap-2">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="min-h-[360px] w-full resize-y rounded-md border border-[var(--border-token)] bg-surface-card p-3 font-mono text-[12.5px] leading-relaxed text-text-primary focus:outline-none focus:ring-2 focus:ring-brand-primary/30"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-muted">
          <div>{value.length.toLocaleString()} chars · ~{tokens.toLocaleString()} tokens</div>
          <div>Est. cost/call: ${(tokens * 0.000002).toFixed(4)}</div>
        </div>
        {undefinedVars.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-[12px] text-amber-800">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              Unknown variable(s): {undefinedVars.map((v) => (
                <code key={v} className="mx-0.5 rounded bg-white/60 px-1 py-0.5 text-[11px]">{`{${v}}`}</code>
              ))}
              {" "}— they won't be substituted at runtime.
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Variables</div>
          <div className="flex flex-wrap gap-1">
            {KNOWN_VARIABLES.map((v) => (
              <button
                key={v}
                onClick={() => insertVar(v)}
                className="rounded border border-[var(--border-token)] bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-secondary hover:border-brand-primary hover:text-brand-primary-dark"
              >
                {`{${v}}`}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            <Sparkles className="h-3 w-3" /> Presets
          </div>
          <div className="flex flex-col gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => onApplyPreset(p)}
                className="rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1.5 text-left text-[12px] hover:border-brand-primary"
              >
                <div className="font-medium text-text-primary">{p.label}</div>
                <div className="text-[11px] text-text-muted">{p.description}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
