import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ExternalLink, Plus, X } from "lucide-react";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { useRedactionRules } from "@/api/redaction";
import type { Guardrails } from "@/data/prompt-studio-seed";
import { Lozenge } from "@/components/ui/lozenge";
import { LoadingState } from "@/components/ui/loading-state";

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
  const rulesLoading = rulesQuery.isLoading;
  const rulesFailed = rulesQuery.isError;
  const piiRows = rules
    ? Object.entries(rules).map(([key, cfg]) => ({
        key,
        label: cfg.label,
        enabled: cfg.enabled,
      }))
    : [];

  return (
    <div className="grid gap-300 lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col gap-250">
        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Prohibited words / phrases</div>
          <div className="flex flex-wrap gap-075">
            {value.prohibited.map((w) => (
              <Lozenge
                key={w} tone="danger">
                {w}
                <button
                  type="button"
                  aria-label={`Remove prohibited phrase ${w}`}
                  title={`Remove ${w}`}
                  onClick={() => update({ prohibited: value.prohibited.filter((p) => p !== w) })}
                  className="hover:text-text-danger-bolder"
                >
                  <X aria-hidden="true" className="h-3 w-3" />
                </button>
              </Lozenge>
            ))}
            {value.prohibited.length === 0 && (
              <span className="text-body-small text-text-subtlest">No words configured</span>
            )}
          </div>
          <div className="mt-100 flex gap-075">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addWord()}
              placeholder="Add word or phrase…"
              className="flex-1 rounded-medium border border-border bg-surface px-100 py-075 text-body-small"
            />
            <button
              onClick={addWord}
              className="inline-flex items-center gap-050 rounded-medium border border-border px-150 py-075 text-body-small hover:bg-surface-sunken"
            >
              <Plus className="h-3.5 w-3.5" /> Add
            </button>
          </div>
        </div>

        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Behavior rules</div>
          <div className="divide-y divide-border rounded-medium border border-border bg-surface">
            {TOGGLES.map((t) => (
              <div key={t.key as string} className="flex items-start justify-between gap-150 px-150 py-150">
                <div>
                  <div className="text-[0.75rem] font-medium text-text">{t.label}</div>
                  <div className="text-body-small text-text-subtlest">{t.hint}</div>
                </div>
                <Switch
                  aria-label={t.label}
                  checked={Boolean(value[t.key])}
                  onCheckedChange={(v) => update({ [t.key]: v } as Partial<Guardrails>)}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-250">
        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Response limits</div>
          <div className="rounded-medium border border-border bg-surface p-150">
            <div className="mb-050 flex items-center justify-between text-body-small">
              <span className="font-medium">Max turns per call</span>
              <span className="font-mono text-body-small text-text-subtle">{value.maxTurns}</span>
            </div>
            <Slider value={[value.maxTurns]} min={4} max={40} step={1} onValueChange={([v]) => update({ maxTurns: v })} />
            <div className="mt-200 mb-050 flex items-center justify-between text-body-small">
              <span className="font-medium">Max call duration</span>
              <span className="font-mono text-body-small text-text-subtle">{Math.round(value.maxSeconds / 60)}m</span>
            </div>
            <Slider value={[value.maxSeconds]} min={120} max={900} step={30} onValueChange={([v]) => update({ maxSeconds: v })} />
          </div>
        </div>

        <div>
          <div className="mb-075 flex items-center justify-between text-body-small font-semibold text-text-subtlest">
            <span>PII redaction (owned by Redaction Hub)</span>
            <Link
              to="/redaction"
              className="inline-flex items-center gap-050 normal-case tracking-normal text-text-brand hover:underline"
            >
              Open hub <ExternalLink className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid grid-cols-2 gap-075">
            {rulesLoading && (
              <div className="col-span-2 rounded-medium border border-dashed border-border px-150 py-150">
                <LoadingState label="Loading redaction rules" />
              </div>
            )}
            {!rulesLoading && rulesFailed && (
              <div className="col-span-2 rounded-medium border border-dashed border-border px-150 py-150 text-body-small text-text-subtlest">
                Could not load redaction rules — this list is not a statement
                about what is redacted.
              </div>
            )}
            {!rulesLoading && !rulesFailed && piiRows.length === 0 && (
              <div className="col-span-2 rounded-medium border border-dashed border-border px-150 py-150 text-body-small text-text-subtlest">
                No redaction rules configured in Redaction Hub.
              </div>
            )}
            {piiRows.map((p) => (
              <div
                key={p.key}
                className="flex items-center gap-100 rounded-medium border border-border bg-surface-sunken px-150 py-100 text-body-small text-text-subtle"
              >
                <span
                  className={`h-100 w-100 rounded-full ${p.enabled ? "bg-background-success-bold" : "bg-background-accent-gray-subtle"}`}
                  title={p.enabled ? "Enabled in Redaction Hub" : "Disabled in Redaction Hub"}
                />
                <span className="truncate">{p.label}</span>
                <span className="ml-auto text-body-small text-text-subtlest">
                  {p.enabled ? "on" : "off"}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-050 text-body-small text-text-subtlest">
            Read-only here — toggle PAN, account, Aadhaar, etc. in Redaction Hub. Studio cannot override them.
          </p>
        </div>
      </div>
    </div>
  );
}
