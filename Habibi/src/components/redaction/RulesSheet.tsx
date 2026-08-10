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
      <SheetContent side="right" className="w-[26.25rem] sm:w-[30rem] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Redaction rules</SheetTitle>
          <SheetDescription>
            Configure which PII categories are auto-masked and the replacement pattern applied on export.
          </SheetDescription>
        </SheetHeader>

        <div className="mt-200 space-y-200 px-050 pb-300">
          <div>
            <div className="mb-075 text-body-small font-semibold text-text-subtlest">Preset policy</div>
            <div className="flex gap-075">
              {(["strict", "balanced", "minimal"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setPolicy(m)}
                  className="flex-1 rounded-medium border border-border px-100 py-075 text-body-small capitalize text-text hover:bg-background-brand-subtlest"
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-100">
            {ENTITY_TYPES.map((t) => {
              const r = rules[t];
              return (
                <div key={t} className="rounded-large border border-border p-150">
                  <div className="flex items-center gap-100">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: ENTITY_COLORS[t] }} />
                    <span className="text-body font-semibold text-text">{r.label}</span>
                    <label className="ml-auto inline-flex cursor-pointer items-center gap-050 text-body-small text-text-subtle">
                      <input
                        type="checkbox"
                        checked={r.enabled}
                        onChange={(e) => onChange({ ...rules, [t]: { ...r, enabled: e.target.checked } })}
                        className="h-3.5 w-3.5 accent-[var(--background-brand-bold)]"
                      />
                      {r.enabled ? "Enabled" : "Disabled"}
                    </label>
                  </div>
                  <div className="mt-100">
                    <label className="mb-050 block text-body-small font-semibold text-text-subtlest">
                      Replacement pattern
                    </label>
                    <input
                      value={r.replacement}
                      onChange={(e) => onChange({ ...rules, [t]: { ...r, replacement: e.target.value } })}
                      className="w-full rounded-medium border border-border bg-surface-sunken px-100 py-050 font-mono text-body-small focus:border-border-brand focus:outline-none"
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
