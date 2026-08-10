import { useEffect, useRef } from "react";
import { Bot, User, Headphones, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDuration, type TranscriptTurn } from "@/data/audit-seed";

interface Props {
  turns: TranscriptTurn[];
  currentTime: number;
  onSeek: (t: number) => void;
}

const SPEAKER_META = {
  bot: { icon: Bot, label: "Bot", tone: "text-text-brand bg-background-brand-subtlest" },
  agent: { icon: Headphones, label: "Agent", tone: "text-text bg-surface-sunken" },
  customer: { icon: User, label: "Customer", tone: "text-text-success bg-[var(--success-bg)]" },
  system: { icon: Info, label: "System", tone: "text-text-subtlest bg-surface-sunken" },
} as const;

export function TranscriptView({ turns, currentTime, onSeek }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  const activeIndex = (() => {
    let idx = -1;
    for (let i = 0; i < turns.length; i++) if (turns[i].t <= currentTime) idx = i;
    return idx;
  })();

  useEffect(() => {
    if (activeIndex < 0 || !containerRef.current) return;
    const el = containerRef.current.querySelector<HTMLElement>(`[data-idx="${activeIndex}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeIndex]);

  return (
    <div ref={containerRef} className="space-y-075">
      {turns.map((turn, i) => {
        const meta = SPEAKER_META[turn.speaker];
        const Icon = meta.icon;
        const active = i === activeIndex;
        return (
          <button
            key={turn.id}
            data-idx={i}
            onClick={() => onSeek(turn.t)}
            className={cn(
              "flex w-full items-start gap-100 rounded-medium border border-transparent p-100 text-left transition-colors",
              active
                ? "border-border-brand/40 bg-background-brand-subtlest"
                : "hover:bg-surface-sunken",
            )}
          >
            <span className={cn("mt-025 inline-flex h-300 w-300 shrink-0 items-center justify-center rounded-full", meta.tone)}>
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="mb-025 flex items-center gap-100 text-body-small">
                <span className="font-semibold text-text">{meta.label}</span>
                <span className="font-mono text-text-subtlest">{formatDuration(turn.t)}</span>
              </div>
              <div className={cn("text-body leading-snug", turn.speaker === "system" ? "italic text-text-subtlest" : "text-text")}>
                {turn.text}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
