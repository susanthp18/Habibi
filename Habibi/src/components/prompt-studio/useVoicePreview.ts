import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { previewTts, type TtsCatalogVoice, type TtsPreviewInput } from "@/api/prompt-studio";

/** The line every voice speaks when you audition it from a list. */
export const VOICE_DEMO_LINE =
  "Hello, this is a sample of how I sound on a collections call.";

/** Neutral delivery for an audition — the point is to compare voices, not tuning. */
const DEMO_DELIVERY = { speed: 1, pitch: 0, warmth: 55, pauseMs: 280 } as const;

type PlayOptions = {
  /**
   * Identifies what is playing, so a list can show a stop button on the right
   * row. Null for a preview that belongs to no row (e.g. the tuning panel
   * auditioning the current configuration).
   */
  tag?: string | null;
  onEnded?: () => void;
};

/**
 * One audio element, one in-flight request, for auditioning catalog voices.
 *
 * Modelled on the playback logic in VoicePanel, which the Sandbox's compact
 * picker had no equivalent of — so choosing between 546 voices there meant
 * reading their names. The two invariants worth keeping in one place are that
 * a superseded request must never start playing (hence `genRef`) and that the
 * object URL is revoked, since each audition holds a whole audio clip.
 *
 * VoicePanel deliberately still owns its own player: it also drives a debounced
 * preview of the *current tuning* (speed/pitch/warmth/style), which this hook
 * does not model. The two never appear on the same screen.
 */
export function useVoicePreview() {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [meta, setMeta] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  // Monotonic: a response from a superseded request must not start playing over
  // the one the user actually asked for.
  const genRef = useRef(0);
  const endedRef = useRef<(() => void) | undefined>(undefined);

  const stopPlayback = useCallback(() => {
    const a = audioRef.current;
    if (a) {
      a.onended = null;
      a.onerror = null;
      a.pause();
      a.removeAttribute("src");
      a.load();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
    setPreviewing(null);
  }, []);

  const stop = useCallback(() => {
    genRef.current += 1;
    stopPlayback();
    setLoading(false);
  }, [stopPlayback]);

  // Revoking the object URL on unmount matters here: these blobs are whole
  // audio clips, and a picker the user scrolls through leaks one per audition.
  useEffect(() => () => stop(), [stop]);

  const play = useCallback(
    async (input: TtsPreviewInput, opts: PlayOptions = {}) => {
      const gen = ++genRef.current;
      stopPlayback();
      setPreviewing(opts.tag ?? null);
      setLoading(true);
      setMeta(null);
      endedRef.current = opts.onEnded;
      try {
        const result = await previewTts(input);
        if (gen !== genRef.current) return;

        const url = URL.createObjectURL(result.blob);
        urlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        const finish = () => {
          setPlaying(false);
          setPreviewing(null);
          endedRef.current?.();
        };
        audio.onended = finish;
        audio.onerror = () => {
          toast.error("Couldn't play synthesized audio");
          finish();
        };
        await audio.play();
        setPlaying(true);
        setMeta(
          [
            result.cacheHit ? "cache hit" : "live synthesize",
            result.voiceName,
            result.latencyMs != null ? `${result.latencyMs}ms` : null,
          ]
            .filter(Boolean)
            .join(" · "),
        );
      } catch (err) {
        if (gen !== genRef.current) return;
        setPreviewing(null);
        opts.onEnded?.();
        toast.error(err instanceof Error ? err.message : "TTS preview failed");
      } finally {
        if (gen === genRef.current) setLoading(false);
      }
    },
    [stopPlayback],
  );

  /** Audition one catalog voice with neutral delivery. Click again to stop. */
  const toggleVoice = useCallback(
    (voice: TtsCatalogVoice) => {
      if (previewing === voice.shortName && (playing || loading)) {
        stop();
        return;
      }
      void play(
        {
          text: VOICE_DEMO_LINE,
          shortName: voice.shortName,
          azureVoiceName: voice.shortName,
          ...DEMO_DELIVERY,
        },
        { tag: voice.shortName },
      );
    },
    [loading, play, playing, previewing, stop],
  );

  return { playing, loading, previewing, meta, play, stop, toggleVoice };
}
