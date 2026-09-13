/** The catalogue voice's detail sheet; the Sandbox's compact picker shows the same one. */
import { useState, type ReactNode } from "react";
import { Play, Square } from "lucide-react";
import { type TtsCatalogVoice } from "@/api/prompt-studio";
import { cn } from "@/lib/utils";
import { tierBadge } from "./VoiceCatalogBrowser";

export function VoiceDetailCard({
  voice,
  onUse,
  onPlay,
  playing,
}: {
  voice: TtsCatalogVoice;
  onUse: () => void;
  onPlay: () => void;
  playing: boolean;
}) {
  const badge = tierBadge(voice);
  const [showRaw, setShowRaw] = useState(false);
  return (
    <div className="p-150">
      <div className="flex items-start justify-between gap-100">
        <div>
          <div className="text-body font-semibold text-text">{voice.displayName}</div>
          <div className="text-body-small text-text-subtlest">
            {voice.localName || voice.displayName}
          </div>
        </div>
        <span
          className={cn(
            "rounded border px-075 py-025 text-body-small font-medium",
            badge.className,
          )}
        >
          {badge.label}
        </span>
      </div>
      <div className="mt-100 space-y-075 text-body-small text-text-subtle">
        <Row
          label="ShortName"
          value={
            <code className="rounded bg-surface-sunken px-050 font-mono text-body-small">
              {voice.shortName}
            </code>
          }
        />
        <Row label="Language" value={`${voice.localeName || "—"} (${voice.locale})`} />
        <Row label="Gender" value={voice.gender} />
        <Row label="Status" value={`${voice.status} · ${voice.voiceType}`} />
        <Row label="Model" value={voice.modelSeries.length ? voice.modelSeries.join(", ") : "—"} />
        <Row
          label="Cost"
          value={
            // The USD band comes from tts_price_tiers, Azure's published list;
            // any other provider's row wears it by default, so the number is
            // shown only for the vendor it describes.
            voice.providerId === "azure" && voice.approxUsdPer1MChars != null
              ? `~$${voice.approxUsdPer1MChars} / 1M chars · approximate`
              : `See ${voice.providerId || "the provider"} pricing`
          }
        />
        {voice.styles.length ? <Row label="Styles" value={voice.styles.join(", ")} /> : null}
        {voice.personalities.length ? (
          <Row label="Personality" value={voice.personalities.join(", ")} />
        ) : null}
        {voice.scenarios.length ? (
          <Row label="Scenarios" value={voice.scenarios.join(", ")} />
        ) : null}
        <Row
          label="Audio"
          value={
            [
              voice.wordsPerMinute != null ? `${voice.wordsPerMinute} wpm` : null,
              voice.sampleRateHertz != null ? `${voice.sampleRateHertz} Hz` : null,
            ]
              .filter(Boolean)
              .join(" · ") || "—"
          }
        />
      </div>
      <div className="mt-150 flex gap-100">
        <button
          type="button"
          onClick={onPlay}
          className="inline-flex flex-1 items-center justify-center gap-075 rounded-medium border border-border px-100 py-075 text-body-small font-medium hover:bg-surface-sunken"
        >
          {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          {playing ? "Stop" : "Play demo"}
        </button>
        <button
          type="button"
          onClick={onUse}
          className="inline-flex flex-1 items-center justify-center rounded-medium bg-background-brand-bold px-100 py-075 text-body-small font-medium text-text-inverse hover:bg-background-brand-bold-pressed"
        >
          Use this voice
        </button>
      </div>
      {voice.raw ? (
        <div className="mt-150 border-t border-border pt-100">
          <button
            type="button"
            className="text-body-small font-medium text-text-subtlest hover:text-text"
            onClick={() => setShowRaw((v) => !v)}
          >
            {showRaw ? "Hide technical" : "Show technical"}
          </button>
          {showRaw ? (
            <pre className="mt-050 max-h-40 overflow-auto rounded bg-surface-sunken p-100 text-body-small leading-relaxed text-text-subtle">
              {JSON.stringify(voice.raw, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-100">
      <div className="text-text-subtlest">{label}</div>
      <div className="min-w-0 break-words">{value}</div>
    </div>
  );
}
