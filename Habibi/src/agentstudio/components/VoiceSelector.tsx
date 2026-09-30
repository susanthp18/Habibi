"use client";

import { ChevronDown, Loader2, Search, Volume2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { getVoicesApiV1UserConfigurationsVoicesProviderGet } from "@/agentstudio/client/sdk.gen";
import type { VoiceInfo, VoicePreviewRequest } from "@/agentstudio/client/types.gen";
import { Button } from "@/agentstudio/components/ui/button";
import { Checkbox } from "@/agentstudio/components/ui/checkbox";
import { Input } from "@/agentstudio/components/ui/input";
import { Label } from "@/agentstudio/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/agentstudio/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/agentstudio/components/ui/select";
import { detailFromError } from "@/agentstudio/lib/apiError";
import { cn } from "@/agentstudio/lib/utils";
import { fetchVoicePreviewUrl, PREVIEW_PROVIDERS } from "@/agentstudio/lib/voicePreview";

// Providers that have MPS voice endpoints
type TTSProviderWithVoices = "elevenlabs" | "deepgram" | "sarvam" | "cartesia" | "dograh" | "rime" | "azure_speech";
const MPS_VOICE_PROVIDERS: TTSProviderWithVoices[] = ["elevenlabs", "deepgram", "sarvam", "cartesia", "dograh", "rime", "azure_speech"];
const ALL_FILTER_VALUE = "__all__";
const TIER_LABELS: Record<string, string> = { neural: "Neural", hd: "HD", mai: "MAI" };

// AgentStudio: what a voice costs to speak, from the region's list price.
const formatCost = (voice: VoiceInfo) => {
    if (voice.cost_per_minute != null) return `≈ $${voice.cost_per_minute.toFixed(3)}/min`;
    if (voice.price_per_million_chars != null) return `$${voice.price_per_million_chars}/1M chars`;
    return null;
};

interface VoiceSelectorProps {
    provider: string;
    value: string;
    onChange: (voiceId: string) => void;
    model?: string;
    language?: string;
    showFilters?: boolean;
    allowManualInput?: boolean;
    className?: string;
    /** AgentStudio: the unsaved delivery on the form; a row's play button
     * previews the voice with these, not with defaults. */
    previewSettings?: Omit<VoicePreviewRequest, "voice">;
    /** AgentStudio: the voice the style belongs to; other voices preview without it, as on a call. */
    styleVoice?: string;
}

export const VoiceSelector: React.FC<VoiceSelectorProps> = ({
    provider,
    value,
    onChange,
    model,
    language,
    showFilters = false,
    allowManualInput = true,
    className,
    previewSettings,
    styleVoice,
}) => {
    const [isOpen, setIsOpen] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");
    const [genderFilter, setGenderFilter] = useState(ALL_FILTER_VALUE);
    const [languageFilter, setLanguageFilter] = useState(ALL_FILTER_VALUE);
    const [accentFilter, setAccentFilter] = useState(ALL_FILTER_VALUE);
    const [tierFilter, setTierFilter] = useState(ALL_FILTER_VALUE);
    const [multilingualOnly, setMultilingualOnly] = useState(false);
    const [stylesOnly, setStylesOnly] = useState(false);
    const [sortByCost, setSortByCost] = useState(false);
    const [isManualInput, setIsManualInput] = useState(false);
    const [manualVoiceId, setManualVoiceId] = useState(value || "");
    const [voices, setVoices] = useState<VoiceInfo[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [playingPreview, setPlayingPreview] = useState<string | null>(null);
    // AgentStudio: a failed preview belongs to its voice; the list stays usable.
    const [previewError, setPreviewError] = useState<{ voiceId: string; message: string } | null>(null);
    const [currentAudio, setCurrentAudio] = useState<HTMLAudioElement | null>(null);

    // Check if provider has MPS voice endpoint
    const hasMPSVoiceEndpoint = useCallback((providerName: string): boolean => {
        return MPS_VOICE_PROVIDERS.includes(providerName.toLowerCase() as TTSProviderWithVoices);
    }, []);

    // Map provider names to API-compatible provider names
    const getProviderKey = useCallback((providerName: string): TTSProviderWithVoices | null => {
        const providerMap: Record<string, TTSProviderWithVoices> = {
            elevenlabs: "elevenlabs",
            deepgram: "deepgram",
            sarvam: "sarvam",
            cartesia: "cartesia",
            dograh: "dograh",
            rime: "rime",
            azure_speech: "azure_speech",
        };
        return providerMap[providerName.toLowerCase()] || null;
    }, []);

    const fetchVoices = useCallback(async () => {
        const providerKey = getProviderKey(provider);
        if (!providerKey) {
            setVoices([]);
            return;
        }

        setIsLoading(true);
        setError(null);

        try {
            const query: { model?: string; language?: string } = {};
            if (model) query.model = model;
            if (language) query.language = language;
            const response = await getVoicesApiV1UserConfigurationsVoicesProviderGet({
                path: { provider: providerKey },
                query: Object.keys(query).length > 0 ? query : undefined,
            });

            if (response.error) {
                setError(detailFromError(response.error, "Failed to load voices"));
                setVoices([]);
                return;
            }
            if (response.data?.voices) {
                setVoices(response.data.voices);
            }
        } catch (err) {
            console.error("Failed to fetch voices:", err);
            setError("Failed to load voices");
            setVoices([]);
        } finally {
            setIsLoading(false);
        }
    }, [provider, model, language, getProviderKey]);

    useEffect(() => {
        if (provider) {
            fetchVoices();
        }
    }, [provider, fetchVoices]);

    // Check if the current value exists in the voices list
    useEffect(() => {
        if (value && voices.length > 0) {
            const voiceExists = voices.some((v) => v.voice_id === value);
            if (!voiceExists && allowManualInput) {
                // If the value doesn't exist in the list, switch to manual input mode
                setIsManualInput(true);
                setManualVoiceId(value);
            } else if (voiceExists) {
                setIsManualInput(false);
            }
        }
    }, [value, voices, allowManualInput]);

    // Cleanup audio on unmount or when popover closes
    useEffect(() => {
        if (!isOpen && currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            setCurrentAudio(null);
            setPlayingPreview(null);
        }
    }, [isOpen, currentAudio]);

    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (currentAudio) {
                currentAudio.pause();
            }
        };
    }, [currentAudio]);

    const filteredVoices = voices.filter((voice) => {
        const searchLower = searchTerm.toLowerCase();
        const matchesSearch = (
            voice.name.toLowerCase().includes(searchLower) ||
            voice.voice_id.toLowerCase().includes(searchLower) ||
            (voice.description?.toLowerCase() || "").includes(searchLower) ||
            (voice.accent?.toLowerCase() || "").includes(searchLower) ||
            (voice.gender?.toLowerCase() || "").includes(searchLower) ||
            (voice.language?.toLowerCase() || "").includes(searchLower)
        );
        if (!matchesSearch) return false;
        if (genderFilter !== ALL_FILTER_VALUE && (voice.gender || "").toLowerCase() !== genderFilter) return false;
        // A multilingual voice counts for every language it speaks.
        const spoken = (voice.locales?.length ? voice.locales : [voice.language || ""]).map((l) => l.toLowerCase());
        if (languageFilter !== ALL_FILTER_VALUE && !spoken.includes(languageFilter)) return false;
        if (accentFilter !== ALL_FILTER_VALUE && (voice.accent || "").toLowerCase() !== accentFilter) return false;
        if (tierFilter !== ALL_FILTER_VALUE && voice.tier !== tierFilter) return false;
        if (multilingualOnly && !voice.multilingual) return false;
        if (stylesOnly && !(voice.styles?.length)) return false;
        return true;
    });
    // Voices native to the language first, then others of that language, then
    // multilingual voices that also speak it (a Tamil list opens on Tamil voices).
    const rankLanguage = (languageFilter !== ALL_FILTER_VALUE ? languageFilter : language || "").toLowerCase();
    const nativeRank = (voice: VoiceInfo) => {
        const own = (voice.language || "").toLowerCase();
        if (!rankLanguage || own === rankLanguage) return 0;
        return own.split("-")[0] === rankLanguage.split("-")[0] ? 1 : 2;
    };
    filteredVoices.sort((a, b) => nativeRank(a) - nativeRank(b));
    if (sortByCost) {
        filteredVoices.sort(
            (a, b) => (a.cost_per_minute ?? Infinity) - (b.cost_per_minute ?? Infinity) || nativeRank(a) - nativeRank(b) || a.name.localeCompare(b.name),
        );
    }

    const genderOptions = Array.from(
        new Set(voices.map((voice) => voice.gender?.toLowerCase()).filter(Boolean) as string[]),
    ).sort();
    const languageOptions = Array.from(
        new Set(
            voices
                .flatMap((voice) => (voice.locales?.length ? voice.locales : [voice.language || ""]))
                .map((locale) => locale.toLowerCase())
                .filter(Boolean),
        ),
    ).sort();
    const tierOptions = Array.from(new Set(voices.map((voice) => voice.tier).filter(Boolean) as string[])).sort();
    const accentOptions = Array.from(
        new Set(voices.map((voice) => voice.accent?.toLowerCase()).filter(Boolean) as string[]),
    ).sort();

    const handleSelectVoice = (voiceId: string) => {
        onChange(voiceId);
        setIsOpen(false);
        setSearchTerm("");
    };

    const handleManualInputToggle = (checked: boolean) => {
        if (!allowManualInput) return;
        setIsManualInput(checked);
        if (checked) {
            setManualVoiceId(value || "");
        } else {
            // When switching back to dropdown, try to find the current value in voices
            const existingVoice = voices.find((v) => v.voice_id === value);
            if (!existingVoice && voices.length > 0) {
                // If current value not in list, select the first voice
                onChange(voices[0]!.voice_id);
            }
        }
    };

    const handleManualVoiceIdChange = (newValue: string) => {
        setManualVoiceId(newValue);
        onChange(newValue);
    };

    const getSelectedVoiceName = () => {
        if (isManualInput && value) {
            return value;
        }
        const voice = voices.find((v) => v.voice_id === value);
        return voice?.name || value || "Select a voice";
    };

    const playPreview = async (previewUrl: string | null, voiceId: string) => {
        // Stop current audio if playing
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            setCurrentAudio(null);
        }

        // If clicking the same voice that's playing, just stop it
        if (playingPreview === voiceId) {
            setPlayingPreview(null);
            return;
        }

        setPlayingPreview(voiceId);
        setPreviewError(null);
        // AgentStudio: voices without a hosted sample are spoken on demand.
        let source = previewUrl;
        if (!source) {
            try {
                // The style goes only to a voice that offers it: MAI voices fail
                // outright on one they lack (Azure 502), standard ones ignore it.
                const offered = voices.find((v) => v.voice_id === voiceId)?.styles ?? [];
                const ownStyle = (styleVoice === undefined || voiceId === styleVoice)
                    && offered.includes(previewSettings?.style ?? "");
                source = await fetchVoicePreviewUrl(provider, {
                    ...previewSettings,
                    ...(ownStyle ? {} : { style: undefined, style_degree: undefined }),
                    voice: voiceId,
                });
            } catch (err) {
                setPreviewError({ voiceId, message: err instanceof Error ? err.message : "Could not preview this voice" });
                setPlayingPreview(null);
                return;
            }
        }
        const release = () => {
            if (!previewUrl) URL.revokeObjectURL(source!);
        };
        const audio = new Audio(source);
        setCurrentAudio(audio);
        audio.onended = () => {
            release();
            setPlayingPreview(null);
            setCurrentAudio(null);
        };
        audio.onerror = () => {
            release();
            setPlayingPreview(null);
            setCurrentAudio(null);
        };
        audio.play().catch(() => {
            release();
            setPlayingPreview(null);
            setCurrentAudio(null);
        });
    };

    // For providers without MPS voice endpoint, show simple input
    if (!hasMPSVoiceEndpoint(provider)) {
        return (
            <div className={cn("space-y-2", className)}>
                <Input
                    type="text"
                    placeholder="Enter voice ID"
                    value={value || ""}
                    onChange={(e) => onChange(e.target.value)}
                />
            </div>
        );
    }

    if (isManualInput && allowManualInput) {
        return (
            <div className={cn("space-y-2", className)}>
                <Input
                    type="text"
                    placeholder="Enter voice ID"
                    value={manualVoiceId}
                    onChange={(e) => handleManualVoiceIdChange(e.target.value)}
                />
                <div className="flex items-center space-x-2">
                    <Checkbox
                        id="manual-voice-input"
                        checked={isManualInput}
                        onCheckedChange={(checked) => handleManualInputToggle(checked as boolean)}
                    />
                    <Label
                        htmlFor="manual-voice-input"
                        className="text-sm font-normal cursor-pointer"
                    >
                        Add Voice ID Manually
                    </Label>
                </div>
            </div>
        );
    }

    return (
        <div className={cn("space-y-2", className)}>
            <Popover open={isOpen} onOpenChange={setIsOpen}>
                <PopoverTrigger asChild>
                    <Button
                        variant="outline"
                        role="combobox"
                        aria-expanded={isOpen}
                        className={cn(
                            "w-full justify-between",
                            !value && "text-muted-foreground"
                        )}
                        disabled={isLoading}
                    >
                        <span className="truncate">
                            {isLoading ? "Loading voices..." : getSelectedVoiceName()}
                        </span>
                        {isLoading ? (
                            <Loader2 className="ml-2 h-4 w-4 shrink-0 animate-spin" />
                        ) : (
                            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                        )}
                    </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[400px] p-0" align="start">
                    <div className="p-2 space-y-2">
                        <div className="relative">
                            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                            <Input
                                placeholder="Search voices..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="pl-8"
                            />
                        </div>

                        {showFilters && (
                            <div className="grid gap-2 sm:grid-cols-3">
                                <Select value={genderFilter} onValueChange={setGenderFilter}>
                                    <SelectTrigger className="h-8">
                                        <SelectValue placeholder="Gender" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value={ALL_FILTER_VALUE}>All genders</SelectItem>
                                        {genderOptions.map((gender) => (
                                            <SelectItem key={gender} value={gender} className="capitalize">
                                                {gender}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>

                                <Select value={languageFilter} onValueChange={setLanguageFilter}>
                                    <SelectTrigger className="h-8">
                                        <SelectValue placeholder="Language" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value={ALL_FILTER_VALUE}>All languages</SelectItem>
                                        {languageOptions.map((voiceLanguage) => (
                                            <SelectItem key={voiceLanguage} value={voiceLanguage} className="uppercase">
                                                {voiceLanguage}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>

                                <Select value={accentFilter} onValueChange={setAccentFilter}>
                                    <SelectTrigger className="h-8">
                                        <SelectValue placeholder="Accent" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value={ALL_FILTER_VALUE}>All accents</SelectItem>
                                        {accentOptions.map((accent) => (
                                            <SelectItem key={accent} value={accent} className="uppercase">
                                                {accent}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>

                                {tierOptions.length > 0 && (
                                    <Select value={tierFilter} onValueChange={setTierFilter}>
                                        <SelectTrigger className="h-8">
                                            <SelectValue placeholder="Tier" />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value={ALL_FILTER_VALUE}>All tiers</SelectItem>
                                            {tierOptions.map((tier) => (
                                                <SelectItem key={tier} value={tier}>
                                                    {TIER_LABELS[tier] ?? tier}
                                                </SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                )}
                                <label className="flex items-center gap-2 text-xs">
                                    <Checkbox checked={multilingualOnly} onCheckedChange={(c) => setMultilingualOnly(c === true)} />
                                    Multilingual
                                </label>
                                <label className="flex items-center gap-2 text-xs">
                                    <Checkbox checked={stylesOnly} onCheckedChange={(c) => setStylesOnly(c === true)} />
                                    Has styles
                                </label>
                                <label className="flex items-center gap-2 text-xs">
                                    <Checkbox checked={sortByCost} onCheckedChange={(c) => setSortByCost(c === true)} />
                                    Cheapest first
                                </label>
                            </div>
                        )}

                        <div className="max-h-[300px] overflow-auto space-y-1">
                            {error ? (
                                <p className="text-sm text-text-danger text-center py-4">
                                    {error}
                                </p>
                            ) : isLoading ? (
                                <div className="flex items-center justify-center py-4">
                                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                </div>
                            ) : filteredVoices.length === 0 ? (
                                <p className="text-sm text-muted-foreground text-center py-4">
                                    No voices found
                                </p>
                            ) : (
                                filteredVoices.map((voice) => (
                                    <div
                                        key={voice.voice_id}
                                        className={cn(
                                            "flex items-start space-x-3 p-2 hover:bg-accent rounded-sm cursor-pointer",
                                            value === voice.voice_id && "bg-accent"
                                        )}
                                        onClick={() => handleSelectVoice(voice.voice_id)}
                                    >
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2">
                                                <p className="text-sm font-medium truncate">
                                                    {voice.name}
                                                </p>
                                                {voice.gender && (
                                                    <span className="text-xs text-muted-foreground capitalize">
                                                        {voice.gender}
                                                    </span>
                                                )}
                                            </div>
                                            {voice.description && (
                                                <p className="text-xs text-muted-foreground line-clamp-2">
                                                    {voice.description}
                                                </p>
                                            )}
                                            {previewError?.voiceId === voice.voice_id && (
                                                <p className="text-xs text-text-danger">{previewError.message}</p>
                                            )}
                                            <div className="flex flex-wrap items-center gap-2 mt-1">
                                                {voice.tier && voice.tier !== "neural" && (
                                                    <span className="text-xs bg-background-warning text-text-warning px-1.5 py-0.5 rounded">
                                                        {TIER_LABELS[voice.tier] ?? voice.tier}
                                                    </span>
                                                )}
                                                {voice.multilingual && (
                                                    <span
                                                        className="text-xs bg-background-information text-text-information px-1.5 py-0.5 rounded"
                                                        title={(voice.locales ?? []).join(", ")}
                                                    >
                                                        Multilingual · {voice.locales?.length ?? 0}
                                                    </span>
                                                )}
                                                {voice.status && voice.status !== "GA" && (
                                                    <span className="text-xs bg-secondary px-1.5 py-0.5 rounded">
                                                        {voice.status}
                                                    </span>
                                                )}
                                                {formatCost(voice) && (
                                                    <span className="text-xs text-muted-foreground">{formatCost(voice)}</span>
                                                )}
                                                {voice.accent && (
                                                    <span className="text-xs bg-secondary px-1.5 py-0.5 rounded capitalize">
                                                        {voice.accent}
                                                    </span>
                                                )}
                                                {voice.language && (
                                                    <span className="text-xs bg-secondary px-1.5 py-0.5 rounded uppercase">
                                                        {voice.language}
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        {(voice.preview_url || PREVIEW_PROVIDERS.has(provider)) && (
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                className="h-8 w-8 p-0 shrink-0"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    void playPreview(voice.preview_url ?? null, voice.voice_id);
                                                }}
                                            >
                                                <Volume2
                                                    className={cn(
                                                        "h-4 w-4",
                                                        playingPreview === voice.voice_id &&
                                                            "text-primary animate-pulse"
                                                    )}
                                                />
                                            </Button>
                                        )}
                                    </div>
                                ))
                            )}
                        </div>

                        <div className="pt-2 border-t flex items-center justify-between">
                            {allowManualInput ? (
                                <div className="flex items-center space-x-2">
                                    <Checkbox
                                        id="manual-voice-input-popup"
                                        checked={isManualInput}
                                        onCheckedChange={(checked) => {
                                            handleManualInputToggle(checked as boolean);
                                            if (checked) {
                                                setIsOpen(false);
                                            }
                                        }}
                                    />
                                    <Label
                                        htmlFor="manual-voice-input-popup"
                                        className="text-sm font-normal cursor-pointer"
                                    >
                                        Add Voice ID Manually
                                    </Label>
                                </div>
                            ) : (
                                <span />
                            )}
                            <p className="text-xs text-muted-foreground">
                                {filteredVoices.length} of {voices.length} voices
                            </p>
                        </div>
                    </div>
                </PopoverContent>
            </Popover>
        </div>
    );
};
