import { useEffect, useRef, useState } from "react";
import { Play, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { Slider } from "@/components/ui/slider";
import { previewTts } from "@/api/prompt-studio";
import {
  LANGUAGES,
  languageTag,
  renderPersonaPreview,
  type PersonaPreset,
  type PersonaState,
  type PersonaTraitKey,
  type VoiceConfig,
} from "@/data/prompt-studio-seed";
import { Lozenge } from "@/components/ui/lozenge";

const TRAITS: Array<{ key: PersonaTraitKey; label: string; lo: string; hi: string }> = [
  { key: "empathy", label: "Empathy", lo: "Transactional", hi: "Warm" },
  { key: "firmness", label: "Firmness", lo: "Soft", hi: "Direct" },
  { key: "formality", label: "Formality", lo: "Casual", hi: "Formal" },
  { key: "verbosity", label: "Verbosity", lo: "Concise", hi: "Detailed" },
  { key: "upsell", label: "Proactive upsell", lo: "Never", hi: "Always" },
];

type Props = {
  value: PersonaState;
  onChange: (next: PersonaState) => void;
  /**
   * Required, and deliberately not defaulted.
   *
   * This used to default to the hardcoded `PRESETS` mock, which is the same
   * failure as the `?? PRESETS` fallback removed from the studio: a tenant with
   * an empty persona_presets table saw four presets that do not exist and could
   * apply a template from nowhere. A default parameter hides it even better
   * than `??` does, because nothing at the call site looks wrong.
   */
  presets: PersonaPreset[];
  /**
   * The studio's preset pipeline — confirmation when authored text would be
   * lost, then a toast whose Undo restores prompt *and* traits.
   *
   * Optional so the component still stands alone, but the studio route must
   * pass it. Without it these chips wrote `traits` straight to local state,
   * which is the same click doing a different thing on two tabs: the Prompt
   * tab asked before overwriting and offered a way back, the Persona tab
   * moved five sliders silently and offered none.
   */
  onApplyPreset?: (preset: PersonaPreset) => void;
  /** Current TTS voice settings — used to speak the persona preview. */
  voice?: VoiceConfig;
};

export function PersonaSliders({ value, onChange, presets, onApplyPreset, voice }: Props) {
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const requestGen = useRef(0);

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

  const stopPlayback = () => {
    const a = audioRef.current;
    if (a) {
      a.onended = null;
      a.pause();
      a.removeAttribute("src");
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    setPlaying(false);
    setLoading(false);
  };

  const stop = () => {
    requestGen.current += 1;
    stopPlayback();
  };

  // Stop playback and revoke the blob URL if the tab unmounts mid-preview
  // (PersonaSliders is conditionally rendered), matching VoicePanel's guard.
  useEffect(() => () => stop(), []);

  const hearPreview = async () => {
    if (playing || loading) {
      stop();
      return;
    }
    if (!voice?.voiceId && !voice?.azureVoiceName) {
      toast.error("Pick a TTS voice in the Voice tab first");
      return;
    }
    const gen = ++requestGen.current;
    stopPlayback();
    const text = renderPersonaPreview(value);
    setLoading(true);
    try {
      const result = await previewTts({
        text,
        voiceId: voice.voiceId,
        shortName: voice.azureVoiceName,
        azureVoiceName: voice.azureVoiceName,
        speed: voice.speed,
        pitch: voice.pitch,
        warmth: voice.warmth,
        pauseMs: voice.pauseMs,
        style: voice.style,
      });
      if (gen !== requestGen.current) return;
      const url = URL.createObjectURL(result.blob);
      urlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      // Release the blob when playback finishes on its own.
      //
      // `stopPlayback` revokes it, and the two paths that call it are Stop and
      // unmount — so a preview the operator simply listens to the end of left
      // its object URL alive for the lifetime of the page. Tuning persona
      // sliders means pressing this repeatedly, and every press allocated
      // another few hundred kilobytes of audio that nothing would ever free.
      audio.onended = () => stopPlayback();
      // Matches VoicePanel. Without it, audio that fails *after* play() resolves
      // leaves the button reading "Stop" with nothing playing and no way back
      // except pressing it — `play()` rejecting is the only case the catch sees.
      audio.onerror = () => {
        toast.error("Couldn’t play the persona preview");
        stopPlayback();
      };
      await audio.play();
      if (gen !== requestGen.current) {
        stopPlayback();
        return;
      }
      setPlaying(true);
    } catch (err) {
      if (gen !== requestGen.current) return;
      toast.error(err instanceof Error ? err.message : "Could not speak preview");
    } finally {
      if (gen === requestGen.current) setLoading(false);
    }
  };

  return (
    <div className="grid gap-300 lg:grid-cols-[1fr_1fr]">
      <div className="flex flex-col gap-250">
        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">Presets</div>
          <div className="flex flex-wrap gap-075">
            {presets.map((p) => (
              <button
                key={p.id}
                // Not "submit". These sit in no form today, so the default did
                // nothing visible — but it is the kind of default that starts
                // reloading the page the day someone wraps the tab in one.
                type="button"
                // A preset is a prompt template *and* a set of traits. Applying
                // half of it here made the same chip mean two different things
                // depending on which tab you clicked it from.
                onClick={() => (onApplyPreset ? onApplyPreset(p) : update({ traits: p.traits }))}
                className="rounded-full border border-border px-150 py-050 text-body-small text-text-subtle hover:border-border-brand hover:text-text-brand"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-200">
          {TRAITS.map((t) => (
            <div key={t.key}>
              <div className="mb-050 flex items-center justify-between text-body-small">
                <span className="font-medium text-text">{t.label}</span>
                <span className="font-mono text-body-small text-text-subtle">
                  {value.traits[t.key]}
                </span>
              </div>
              <Slider
                value={[value.traits[t.key]]}
                min={0}
                max={100}
                step={1}
                onValueChange={([v]) => setTrait(t.key, v)}
              />
              <div className="mt-025 flex justify-between text-body-small text-text-subtlest">
                <span>{t.lo}</span>
                <span>{t.hi}</span>
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="mb-075 text-body-small font-semibold text-text-subtlest">
            Primary language
          </div>
          <select
            value={value.language}
            onChange={(e) => update({ language: e.target.value })}
            className="w-full rounded-medium border border-border bg-surface px-100 py-075 text-body-small"
          >
            {LANGUAGES.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
          {/* The tag, because this control now binds the recogniser and there is
              no other place in the Studio that says so. It was inert on voice
              until recently: the tab wrote a display name, the recogniser read
              AgentTuning.stt.language, and nothing connected them — so Hindi
              could be selected, saved and dialled while the call listened in
              en-IN. Naming the tag is what makes the link checkable. */}
          <p className="mt-050 text-body-small text-text-subtlest">
            Sets what the agent speaks and what speech recognition listens for (
            <code className="font-mono">{languageTag(value.language) ?? "unmapped"}</code>). A
            per-session override in the Sandbox&apos;s Tuning Studio still wins.
          </p>
          <div className="mt-100 text-body-small text-text-subtlest">Vernacular fallbacks</div>
          <div className="mt-050 flex flex-wrap gap-050">
            {LANGUAGES.filter((l) => l !== value.language).map((l) => {
              const on = value.fallbackLanguages.includes(l);
              return (
                <button
                  key={l}
                  onClick={() => toggleFallback(l)}
                  className={`rounded-full px-100 py-025 text-body-small ${
                    on
                      ? "bg-background-brand-bold text-white"
                      : "border border-border bg-surface text-text-subtle hover:border-border-brand"
                  }`}
                >
                  {l}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="rounded-large border border-border bg-surface-sunken p-200">
        <div className="mb-100 flex items-center justify-between">
          <div className="text-body-small font-semibold text-text-subtlest">Persona preview</div>
          <button
            type="button"
            onClick={() => void hearPreview()}
            disabled={loading}
            className="inline-flex items-center gap-050 rounded-medium border border-border bg-surface px-100 py-050 text-body-small hover:bg-surface disabled:opacity-50"
          >
            {playing || loading ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {loading ? "Synthesizing…" : playing ? "Stop" : "Hear tone"}
          </button>
        </div>
        <div className="rounded-medium border border-border bg-surface p-150 text-body leading-relaxed text-text">
          <Lozenge tone="selected" className="mr-100">
            bot
          </Lozenge>
          {renderPersonaPreview(value)}
        </div>
        <p className="mt-100 flex items-start gap-075 text-body-small text-text-subtlest">
          <Volume2 className="mt-025 h-3.5 w-3.5 shrink-0" />
          Spoken with the Voice tab’s TTS settings (warmth/pitch/speed). Adjust sliders, then Hear
          tone.
        </p>
      </div>
    </div>
  );
}
