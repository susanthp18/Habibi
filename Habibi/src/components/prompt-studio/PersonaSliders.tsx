import { Slider } from "@/components/ui/slider";
import { LANGUAGES, PRESETS, renderPersonaPreview, type PersonaState, type PersonaTraitKey } from "@/data/prompt-studio-seed";

const TRAITS: Array<{ key: PersonaTraitKey; label: string; lo: string; hi: string }> = [
  { key: "empathy", label: "Empathy", lo: "Transactional", hi: "Warm" },
  { key: "firmness", label: "Firmness", lo: "Soft", hi: "Direct" },
  { key: "formality", label: "Formality", lo: "Casual", hi: "Formal" },
  { key: "verbosity", label: "Verbosity", lo: "Concise", hi: "Detailed" },
  { key: "upsell", label: "Proactive Upsell", lo: "Never", hi: "Always" },
];

type Props = {
  value: PersonaState;
  onChange: (next: PersonaState) => void;
};

export function PersonaSliders({ value, onChange }: Props) {
  const update = (patch: Partial<PersonaState>) => onChange({ ...value, ...patch });
  const setTrait = (k: PersonaTraitKey, v: number) =>
    onChange({ ...value, traits: { ...value.traits, [k]: v } });

  const toggleFallback = (lang: string) => {
    const has = value.fallbackLanguages.includes(lang);
    update({
      fallbackLanguages: has
        ? value.fallbackLanguages.filter((l) => l !== lang)
        : [...value.fallbackLanguages, lang],
    });
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col gap-5">
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Presets</div>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => update({ traits: p.traits })}
                className="rounded-full border border-[var(--border-token)] px-2.5 py-1 text-[11.5px] text-text-secondary hover:border-brand-primary hover:text-brand-primary-dark"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4">
          {TRAITS.map((t) => (
            <div key={t.key}>
              <div className="mb-1 flex items-center justify-between text-[12px]">
                <span className="font-medium text-text-primary">{t.label}</span>
                <span className="font-mono text-[11px] text-text-secondary">{value.traits[t.key]}</span>
              </div>
              <Slider
                value={[value.traits[t.key]]}
                min={0}
                max={100}
                step={1}
                onValueChange={([v]) => setTrait(t.key, v)}
              />
              <div className="mt-0.5 flex justify-between text-[10px] text-text-muted">
                <span>{t.lo}</span>
                <span>{t.hi}</span>
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Primary language</div>
          <select
            value={value.language}
            onChange={(e) => update({ language: e.target.value })}
            className="w-full rounded-md border border-[var(--border-token)] bg-surface-card px-2 py-1.5 text-[12.5px]"
          >
            {LANGUAGES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
          <div className="mt-2 text-[11px] text-text-muted">Vernacular fallbacks</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {LANGUAGES.filter((l) => l !== value.language).map((l) => {
              const on = value.fallbackLanguages.includes(l);
              return (
                <button
                  key={l}
                  onClick={() => toggleFallback(l)}
                  className={`rounded-full px-2 py-0.5 text-[11px] ${
                    on
                      ? "bg-brand-primary text-white"
                      : "border border-[var(--border-token)] bg-surface-card text-text-secondary hover:border-brand-primary"
                  }`}
                >
                  {l}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-[var(--border-token)] bg-surface-sunken p-4">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Persona preview</div>
        <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3 text-[13px] leading-relaxed text-text-primary">
          <span className="mr-2 rounded-full bg-brand-tint px-1.5 py-0.5 text-[10px] font-medium uppercase text-brand-primary-dark">
            bot
          </span>
          {renderPersonaPreview(value)}
        </div>
        <p className="mt-2 text-[11px] text-text-muted">
          Auto-generated from current trait mix. Adjust sliders to hear the tone shift.
        </p>
      </div>
    </div>
  );
}
