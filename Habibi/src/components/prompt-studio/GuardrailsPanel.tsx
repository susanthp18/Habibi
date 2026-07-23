import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ExternalLink, Plus, X } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useRedactionRules } from "@/api/redaction";
import type { Guardrails } from "@/data/prompt-studio-seed";

type Props = {
  value: Guardrails;
  onChange: (next: Guardrails) => void;
};

const TOGGLES: Array<{ key: keyof Guardrails; label: string; hint: string }> = [
  { key: "escalateAbuse", label: "Escalate on abusive language", hint: "Hard flag + handoff when customer uses abuse" },
  { key: "escalateLegal", label: "Escalate on legal threats", hint: "Court / lawyer intents auto-escalate" },
  { key: "neverQuoteRate", label: "Never quote interest rate", hint: "Hard-blocks APR / % rate quotes in bot replies" },
  { key: "neverPromiseWaiver", label: "Never promise fee waivers", hint: "Hard-blocks waiver promises (goodwill review ok)" },
  { key: "alwaysDiscloseRecording", label: "Always disclose recording", hint: "Flags missing disclosure on turn 1" },
  { key: "refusePoliticsReligion", label: "Refuse politics / religion topics", hint: "Hard-blocks political/religious digressions" },
];

export function GuardrailsPanel({ value, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const rulesQuery = useRedactionRules();
  const update = (patch: Partial<Guardrails>) => onChange({ ...value, ...patch });

  const addWord = () => {
    const w = draft.trim().toLowerCase();
    if (!w || value.prohibited.includes(w)) return;
    update({ prohibited: [...value.prohibited, w] });
    setDraft("");
  };

  const rules = rulesQuery.data;
  const piiRows = rules
    ? Object.entries(rules).map(([key, cfg]) => ({
        key,
        label: cfg.label,
        enabled: cfg.enabled,
      }))
    : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col gap-5">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Prohibited words / phrases</div>
          <div className="flex flex-wrap gap-1.5">
            {value.prohibited.map((w) => (
              <span
                key={w}
                className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[11.5px] text-red-700"
              >
                {w}
                <button
                  onClick={() => update({ prohibited: value.prohibited.filter((p) => p !== w) })}
                  className="hover:text-red-900"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {value.prohibited.length === 0 && (
              <span className="text-[11px] text-text-muted">No words configured</span>
            )}
          </div>
          <div className="mt-2 flex gap-1.5">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addWord()}
              placeholder="Add word or phrase…"
              className="flex-1 rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1.5 text-[12.5px]"
            />
            <button
              onClick={addWord}
              className="inline-flex items-center gap-1 rounded-md border border-[var(--border-token)] px-2.5 py-1.5 text-[12px] hover:bg-surface-sunken"
            >
              <Plus className="h-3.5 w-3.5" /> Add
            </button>
          </div>
        </div>

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Behavior rules</div>
          <div className="divide-y divide-[var(--border-token)] rounded-md border border-[var(--border-token)] bg-surface-card">
            {TOGGLES.map((t) => (
              <div key={t.key as string} className="flex items-start justify-between gap-3 px-3 py-2.5">
                <div>
                  <div className="text-[12.5px] font-medium text-text-primary">{t.label}</div>
                  <div className="text-[11px] text-text-muted">{t.hint}</div>
                </div>
                <Switch
                  checked={Boolean(value[t.key])}
                  onCheckedChange={(v) => update({ [t.key]: v } as Partial<Guardrails>)}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-5">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Response limits</div>
          <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3">
            <div className="mb-1 flex items-center justify-between text-[12px]">
              <span className="font-medium">Max turns per call</span>
              <span className="font-mono text-[11px] text-text-secondary">{value.maxTurns}</span>
            </div>
            <Slider value={[value.maxTurns]} min={4} max={40} step={1} onValueChange={([v]) => update({ maxTurns: v })} />
            <div className="mt-4 mb-1 flex items-center justify-between text-[12px]">
              <span className="font-medium">Max call duration</span>
              <span className="font-mono text-[11px] text-text-secondary">{Math.round(value.maxSeconds / 60)}m</span>
            </div>
            <Slider value={[value.maxSeconds]} min={120} max={900} step={30} onValueChange={([v]) => update({ maxSeconds: v })} />
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-text-muted">
            <span>PII redaction (owned by Redaction Hub)</span>
            <Link
              to="/redaction"
              className="inline-flex items-center gap-1 normal-case tracking-normal text-brand-primary hover:underline"
            >
              Open hub <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {piiRows.length === 0 && (
              <div className="col-span-2 rounded-md border border-dashed border-[var(--border-token)] px-2.5 py-3 text-[12px] text-text-muted">
                Loading redaction rules…
              </div>
            )}
            {piiRows.map((p) => (
              <div
                key={p.key}
                className="flex items-center gap-2 rounded-md border border-[var(--border-token)] bg-surface-sunken px-2.5 py-2 text-[12.5px] text-text-secondary"
              >
                <span
                  className={`h-2 w-2 rounded-full ${p.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
                  title={p.enabled ? "Enabled in Redaction Hub" : "Disabled in Redaction Hub"}
                />
                <span className="truncate">{p.label}</span>
                <span className="ml-auto text-[10px] uppercase text-text-muted">
                  {p.enabled ? "on" : "off"}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-text-muted">
            Read-only here — toggle PAN, account, Aadhaar, etc. in Redaction Hub. Studio cannot override them.
          </p>
        </div>
      </div>
    </div>
  );
}
