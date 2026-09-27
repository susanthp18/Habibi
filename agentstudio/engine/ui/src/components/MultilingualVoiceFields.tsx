"use client";

// AgentStudio: settings for agents whose callers speak several languages --
// the languages to listen for, and the voice that answers in each.
import type { VoicePreviewRequest } from "@/client/types.gen";
import { Checkbox } from "@/components/ui/checkbox";
import { VoiceSelector } from "@/components/VoiceSelector";
import { LANGUAGE_DISPLAY_NAMES } from "@/constants/languages";

// Azure has no mid-sentence mixing for these, and no keyword boosting.
const NO_MIXING = new Set(["ta-IN", "ar-AE"]);
const RECOMMENDED_MAX = 3;

export const languageLabel = (code: string) => LANGUAGE_DISPLAY_NAMES[code] ?? code;

/** List and map settings travel through the form as JSON text. */
export const parseList = (value: unknown): string[] => {
    if (Array.isArray(value)) return value.map(String);
    if (typeof value !== "string" || !value) return [];
    try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed.map(String) : [];
    } catch {
        return value.split(",").map((part) => part.trim()).filter(Boolean);
    }
};

export const parseMap = (value: unknown): Record<string, string> => {
    if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, string>;
    if (typeof value !== "string" || !value) return {};
    try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
};

export function LanguageListField({
    options,
    value,
    primary,
    mode,
    onChange,
}: {
    options: string[];
    value: string[];
    primary?: string;
    mode?: string;
    onChange: (languages: string[]) => void;
}) {
    const chosen = new Set([...(primary ? [primary] : []), ...value]);
    const toggle = (code: string, on: boolean) => {
        const next = new Set(chosen);
        if (on) next.add(code);
        else if (code !== primary) next.delete(code);
        onChange(Array.from(next));
    };
    const blocked = mode === "multilingual" ? Array.from(chosen).filter((code) => NO_MIXING.has(code)) : [];
    return (
        <div className="space-y-2">
            <div className="grid grid-cols-2 gap-1 max-h-48 overflow-auto rounded-md border p-2">
                {options.map((code) => (
                    <label key={code} className="flex items-center gap-2 text-sm">
                        <Checkbox
                            checked={chosen.has(code)}
                            disabled={code === primary}
                            onCheckedChange={(checked) => toggle(code, checked === true)}
                        />
                        {languageLabel(code)}
                    </label>
                ))}
            </div>
            {mode === "single" && chosen.size > 1 && (
                <p className="text-xs text-amber-600">
                    Set language detection to switching between sentences, or only the main language is heard.
                </p>
            )}
            {chosen.size > RECOMMENDED_MAX && (
                <p className="text-xs text-amber-600">
                    More than {RECOMMENDED_MAX} languages makes switching less reliable; give each market its own agent.
                </p>
            )}
            {blocked.length > 0 && (
                <p className="text-xs text-red-600">
                    Mixing within a sentence is not available for {blocked.map(languageLabel).join(", ")}.
                </p>
            )}
            <p className="text-xs text-muted-foreground">
                List every language callers may use: a language that is not listed is misheard as one that is.
            </p>
        </div>
    );
}

export function VoiceMapField({
    provider,
    languages,
    value,
    fallbackVoice,
    previewSettings,
    onChange,
}: {
    provider: string;
    languages: string[];
    value: Record<string, string>;
    fallbackVoice?: string;
    previewSettings?: Omit<VoicePreviewRequest, "voice" | "language">;
    onChange: (voiceMap: Record<string, string>) => void;
}) {
    if (languages.length < 2) {
        return (
            <p className="text-xs text-muted-foreground">
                Add languages under Transcriber to pick a voice for each.
            </p>
        );
    }
    return (
        <div className="space-y-2">
            {languages.map((code) => (
                <div key={code} className="grid grid-cols-[9rem_1fr] items-center gap-2">
                    <span className="text-sm">{languageLabel(code)}</span>
                    <VoiceSelector
                        provider={provider}
                        language={code}
                        showFilters
                        value={value[code] ?? ""}
                        // Styles belong to the agent's own voice, as on a call.
                        previewSettings={{ ...previewSettings, language: code }}
                        styleVoice={fallbackVoice ?? ""}
                        onChange={(voice) => onChange({ ...value, [code]: voice })}
                    />
                </div>
            ))}
            <p className="text-xs text-muted-foreground">
                Each reply is spoken by the voice for its language{fallbackVoice ? `; anything else by ${fallbackVoice}` : ""}.
                The list shows voices that speak the language, multilingual ones included.
            </p>
        </div>
    );
}
