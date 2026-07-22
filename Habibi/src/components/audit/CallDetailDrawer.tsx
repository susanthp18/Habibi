import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "@tanstack/react-router";
import {
  X,
  Phone,
  MessageCircle,
  MessageSquare,
  Bot,
  User,
  ArrowLeftRight,
  ShieldCheck,
  ShieldX,
  Lock,
  ExternalLink,
} from "lucide-react";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AudioPlayer } from "./AudioPlayer";
import { SentimentTimeline } from "./SentimentTimeline";
import { TranscriptView } from "./TranscriptView";
import {
  formatDateTime,
  formatDuration,
  type CallRecord,
} from "@/data/audit-seed";

interface Props {
  call: CallRecord | null;
  onClose: () => void;
}

const CHANNEL_ICON = { voice: Phone, whatsapp: MessageCircle, sms: MessageSquare } as const;

export function CallDetailDrawer({ call, onClose }: Props) {
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);

  useEffect(() => {
    setCurrentTime(0);
    setPlaying(false);
    setSpeed(1);
  }, [call?.id]);

  useEffect(() => {
    if (!playing || !call) return;
    lastTickRef.current = performance.now();
    const tick = (now: number) => {
      const dt = (now - lastTickRef.current) / 1000;
      lastTickRef.current = now;
      setCurrentTime((t) => {
        const next = t + dt * speed;
        if (next >= call.duration) {
          setPlaying(false);
          return call.duration;
        }
        return next;
      });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [playing, speed, call]);

  const markers = useMemo(() => {
    if (!call) return [];
    return [
      ...call.disclosures.filter((d) => d.read && d.atSec != null).map((d) => ({
        t: d.atSec!,
        tone: "var(--success)",
        label: `Disclosure: ${d.label}`,
      })),
      ...call.flags.map((f) => ({
        t: Math.max(4, call.duration * 0.6),
        tone: "var(--danger)",
        label: `Flag: ${f}`,
      })),
    ];
  }, [call]);

  if (!call) return null;

  const ChIcon = CHANNEL_ICON[call.channel];
  const disclosuresRead = call.disclosures.filter((d) => d.read).length;

  return (
    <Sheet open={!!call} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="flex w-full max-w-none flex-col gap-0 p-0 sm:max-w-[720px]"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-[var(--border-token)] px-5 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[12px] text-text-muted">
                <ChIcon className="h-3.5 w-3.5" />
                <span className="capitalize">{call.channel}</span>
                <span>·</span>
                <span>{formatDateTime(call.startedAt)}</span>
                <span>·</span>
                <span className="font-mono">{formatDuration(call.duration)}</span>
                <span>·</span>
                <span className="inline-flex items-center gap-1 rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px]">
                  <Lock className="h-3 w-3" /> immutable
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <h2 className="truncate text-[16px] font-semibold text-brand-navy">
                  {call.customerName}
                </h2>
                <span className="text-[12px] text-text-secondary">{call.phoneMasked}</span>
                <span className="text-[12px] text-text-muted">· {call.accountId}</span>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px]">
                <span className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] font-medium text-brand-primary-dark">
                  {call.disposition}
                </span>
                {call.handledBy.kind === "bot" && (
                  <span className="inline-flex items-center gap-1 text-text-secondary">
                    <Bot className="h-3.5 w-3.5" /> {call.handledBy.bot}
                  </span>
                )}
                {call.handledBy.kind === "human" && (
                  <span className="inline-flex items-center gap-1 text-text-secondary">
                    <User className="h-3.5 w-3.5" /> {call.handledBy.agent}
                  </span>
                )}
                {call.handledBy.kind === "handoff" && (
                  <span className="inline-flex items-center gap-1 text-text-secondary">
                    <ArrowLeftRight className="h-3.5 w-3.5" /> {call.handledBy.bot} → {call.handledBy.agent}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button asChild variant="outline" size="sm" className="h-8 gap-1 text-[12px]">
                <Link to="/customers/$customerId" params={{ customerId: call.customerId }}>
                  Customer 360
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </Button>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Player + sentiment */}
        <div className="shrink-0 space-y-3 border-b border-[var(--border-token)] bg-surface-sunken px-5 py-3">
          <AudioPlayer
            duration={call.duration}
            currentTime={currentTime}
            playing={playing}
            speed={speed}
            onSeek={(t) => setCurrentTime(t)}
            onPlayPause={() => setPlaying((p) => !p)}
            onSpeedChange={setSpeed}
            seedForBars={call.id}
          />
          <SentimentTimeline
            points={call.sentimentSeries}
            duration={call.duration}
            currentTime={currentTime}
            markers={markers}
            onSeek={setCurrentTime}
          />
        </div>

        {/* Tabs */}
        <Tabs defaultValue="transcript" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="mx-5 mt-3 shrink-0 self-start">
            <TabsTrigger value="transcript">Transcript</TabsTrigger>
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="disclosures">
              Disclosures
              <span className="ml-1.5 rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-mono">
                {disclosuresRead}/{call.disclosures.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="meta">Metadata</TabsTrigger>
          </TabsList>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-3">
            <TabsContent value="transcript" className="mt-0">
              <TranscriptView turns={call.transcript} currentTime={currentTime} onSeek={setCurrentTime} />
            </TabsContent>

            <TabsContent value="summary" className="mt-0 space-y-3">
              <div className="rounded-md border border-[var(--border-token)] bg-surface-card p-3 text-[13px] leading-relaxed text-text-primary">
                {call.summary}
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Tags</div>
                <div className="flex flex-wrap gap-1.5">
                  {call.tags.length === 0 ? (
                    <span className="text-[12px] text-text-muted">No tags.</span>
                  ) : (
                    call.tags.map((t) => (
                      <span key={t} className="rounded-full bg-brand-tint px-2 py-0.5 text-[11px] text-brand-primary-dark">
                        #{t}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-text-muted">Flags</div>
                <div className="flex flex-wrap gap-1.5">
                  {call.flags.length === 0 ? (
                    <span className="text-[12px] text-[var(--success)]">Clean call — no flags.</span>
                  ) : (
                    call.flags.map((f) => (
                      <span key={f} className="rounded-full bg-[var(--danger-bg)] px-2 py-0.5 text-[11px] font-medium text-[var(--danger)]">
                        {f}
                      </span>
                    ))
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="disclosures" className="mt-0">
              <ul className="divide-y divide-[var(--border-token)] rounded-md border border-[var(--border-token)] bg-surface-card">
                {call.disclosures.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 px-3 py-2">
                    <div className="flex items-center gap-2">
                      {d.read ? (
                        <ShieldCheck className="h-4 w-4 text-[var(--success)]" />
                      ) : (
                        <ShieldX className="h-4 w-4 text-[var(--danger)]" />
                      )}
                      <span className="text-[13px] text-text-primary">{d.label}</span>
                    </div>
                    <div className="text-[11px]">
                      {d.read ? (
                        <span className="font-mono text-text-secondary">at {formatDuration(d.atSec ?? 0)}</span>
                      ) : (
                        <span className="font-medium text-[var(--danger)]">Missed</span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              {call.disclosures.some((d) => !d.read) && (
                <div className="mt-2 rounded-md bg-[var(--danger-bg)] px-3 py-2 text-[12px] text-[var(--danger)]">
                  Missed disclosures on this call may fail compliance review.
                </div>
              )}
            </TabsContent>

            <TabsContent value="meta" className="mt-0">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px]">
                <MetaRow k="Call ID" v={call.id} mono />
                <MetaRow k="Log hash" v={`sha256:${call.hash}…`} mono />
                <MetaRow k="Direction" v={call.direction} />
                <MetaRow k="Channel" v={call.channel} />
                <MetaRow k="Duration" v={formatDuration(call.duration)} mono />
                <MetaRow k="Avg. latency" v={`${call.latencyMs} ms`} mono />
                <MetaRow k="RAG hits" v={String(call.ragHits)} mono />
                <MetaRow k="Redaction" v={call.redactionApplied ? "PII masked" : "Raw"} />
                <MetaRow k="Routing" v={call.routing.join(" → ")} full />
              </dl>
            </TabsContent>
          </div>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

function MetaRow({ k, v, mono, full }: { k: string; v: string; mono?: boolean; full?: boolean }) {
  return (
    <div className={cn("border-b border-[var(--border-token)] pb-1.5", full && "col-span-2")}>
      <dt className="text-[11px] uppercase tracking-wide text-text-muted">{k}</dt>
      <dd className={cn("text-text-primary", mono && "font-mono text-[12px]")}>{v}</dd>
    </div>
  );
}
