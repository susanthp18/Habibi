import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "@/components/ui/sheet";
import { ENTITY_TYPES, ENTITY_COLORS, type RedactionRules } from "@/data/redaction-seed";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  rules: RedactionRules;
  onChange: (rules: RedactionRules) => void;
}

export function RulesSheet({ open, onOpenChange, rules, onChange }: Props) {
  const setPolicy = (mode: "strict" | "balanced" | "minimal") => {
    const next = { ...rules };
    for (const t of ENTITY_TYPES) {
      if (mode === "strict") next[t] = { ...next[t], enabled: true };
      else if (mode === "minimal") next[t] = { ...next[t], enabled: t === "card" || t === "aadhaar" };
      else next[t] = { ...next[t], enabled: t !== "address" && t !== "ifsc" && t !== "custom" };
    }
    onChange(next);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[420px] sm:w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Redaction rules</SheetTitle>
          <SheetDescription>
            Configure which PII categories are auto-masked and the replacement pattern applied on export.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-4 px-1 pb-6">
          <div>
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Preset policy</div>
            <div className="flex gap-1.5">
              {(["strict", "balanced", "minimal"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setPolicy(m)}
                  className="flex-1 rounded-md border border-[var(--border-token)] px-2 py-1.5 text-[12px] capitalize text-text-primary hover:bg-brand-tint"
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            {ENTITY_TYPES.map((t) => {
              const r = rules[t];
              return (
                <div key={t} className="rounded-lg border border-[var(--border-token)] p-3">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: ENTITY_COLORS[t] }} />
                    <span className="text-[13px] font-semibold text-brand-navy">{r.label}</span>
                    <label className="ml-auto inline-flex cursor-pointer items-center gap-1 text-[11px] text-text-secondary">
                      <input
                        type="checkbox"
                        checked={r.enabled}
                        onChange={(e) => onChange({ ...rules, [t]: { ...r, enabled: e.target.checked } })}
                        className="h-3.5 w-3.5 accent-[var(--brand-primary)]"
                      />
                      {r.enabled ? "Enabled" : "Disabled"}
                    </label>
                  </div>
                  <div className="mt-2">
                    <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                      Replacement pattern
                    </label>
                    <input
                      value={r.replacement}
                      onChange={(e) => onChange({ ...rules, [t]: { ...r, replacement: e.target.value } })}
                      className="w-full rounded-md border border-[var(--border-token)] bg-surface-sunken px-2 py-1 font-mono text-[12px] focus:border-brand-primary focus:outline-none"
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
