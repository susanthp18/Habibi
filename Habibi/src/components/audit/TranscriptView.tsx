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
  bot: { icon: Bot, label: "Bot", tone: "text-brand-primary-dark bg-brand-tint" },
  agent: { icon: Headphones, label: "Agent", tone: "text-text-primary bg-surface-sunken" },
  customer: { icon: User, label: "Customer", tone: "text-[var(--success)] bg-[var(--success-bg)]" },
  system: { icon: Info, label: "System", tone: "text-text-muted bg-surface-sunken" },
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
    <div ref={containerRef} className="space-y-1.5">
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
              "flex w-full items-start gap-2 rounded-md border border-transparent p-2 text-left transition-colors",
              active
                ? "border-brand-primary/40 bg-brand-tint"
                : "hover:bg-surface-sunken",
            )}
          >
            <span className={cn("mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full", meta.tone)}>
              <Icon className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="mb-0.5 flex items-center gap-2 text-[11px]">
                <span className="font-semibold text-text-primary">{meta.label}</span>
                <span className="font-mono text-text-muted">{formatDuration(turn.t)}</span>
              </div>
              <div className={cn("text-[13px] leading-snug", turn.speaker === "system" ? "italic text-text-muted" : "text-text-primary")}>
                {turn.text}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}
