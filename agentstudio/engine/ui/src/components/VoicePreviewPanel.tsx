"use client";

// AgentStudio: hear the voice with the unsaved settings on the form (style,
// strength, pitch, speed, volume) before saving them to the agent.
import { Loader2, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { VoicePreviewRequest } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { fetchVoicePreviewUrl } from "@/lib/voicePreview";

const DEFAULT_TEXT =
    "Hello, this is a courtesy call about your account. I can help you with your payment today. Is now a good time?";

export const VoicePreviewPanel = ({
    provider,
    settings,
}: {
    provider: string;
    settings: Omit<VoicePreviewRequest, "text">;
}) => {
    const [text, setText] = useState(DEFAULT_TEXT);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const audio = useRef<HTMLAudioElement | null>(null);
    const url = useRef<string | null>(null);

    const release = () => {
        audio.current?.pause();
        audio.current = null;
        if (url.current) URL.revokeObjectURL(url.current);
        url.current = null;
    };
    useEffect(() => release, []);

    const play = async () => {
        release();
        setError(null);
        setLoading(true);
        try {
            url.current = await fetchVoicePreviewUrl(provider, { ...settings, text });
            audio.current = new Audio(url.current);
            await audio.current.play();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Could not preview this voice");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-2 rounded-md border p-3">
            <Label htmlFor="voice-preview-text">Preview with these settings</Label>
            <Textarea
                id="voice-preview-text"
                rows={2}
                maxLength={300}
                value={text}
                onChange={(e) => setText(e.target.value)}
            />
            <div className="flex items-center gap-3">
                <Button type="button" variant="outline" size="sm" disabled={!settings.voice || loading} onClick={play}>
                    {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Volume2 className="mr-2 h-4 w-4" />}
                    Play
                </Button>
                <p className="text-xs text-muted-foreground">
                    Uses the unsaved values above; save to apply them to calls.
                </p>
            </div>
            {error && (
                <p role="alert" className="text-xs text-destructive">
                    {error}
                </p>
            )}
        </div>
    );
};
