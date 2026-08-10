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
import { Lozenge } from "@/components/ui/lozenge";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { TurnTraceView } from "@/components/trace/TurnTraceView";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AudioPlayer } from "./AudioPlayer";
import { CallCostPanel } from "./CallCostPanel";
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
        className="flex w-full max-w-none flex-col gap-0 p-0 sm:max-w-[50rem]"
      >
        {/* Header */}
        <div className="shrink-0 border-b border-border px-250 py-150">
          <div className="flex items-start justify-between gap-150">
            <div className="min-w-0">
              <div className="flex items-center gap-100 text-body-small text-text-subtlest">
                <ChIcon className="h-3.5 w-3.5" />
                <span className="capitalize">{call.channel}</span>
                <span>·</span>
                <span>{formatDateTime(call.startedAt)}</span>
                <span>·</span>
                <span className="font-mono">{formatDuration(call.duration)}</span>
                <span>·</span>
                <span className="inline-flex items-center gap-050 rounded bg-surface-sunken px-075 py-025 font-mono text-body-small">
                  <Lock className="h-3 w-3" /> immutable
                </span>
              </div>
              <div className="mt-050 flex items-center gap-100">
                <h2 className="truncate text-[0.875rem] font-semibold text-text">
                  {call.customerName}
                </h2>
                <span className="text-body-small text-text-subtle">{call.phoneMasked}</span>
                <span className="text-body-small text-text-subtlest">· {call.accountId}</span>
              </div>
              <div className="mt-075 flex flex-wrap items-center gap-100 text-body-small">
                <Lozenge tone="selected">
                  {call.disposition}
                </Lozenge>
                {call.handledBy.kind === "bot" && (
                  <span className="inline-flex items-center gap-050 text-text-subtle">
                    <Bot className="h-3.5 w-3.5" /> {call.handledBy.bot}
                  </span>
                )}
                {call.handledBy.kind === "human" && (
                  <span className="inline-flex items-center gap-050 text-text-subtle">
                    <User className="h-3.5 w-3.5" /> {call.handledBy.agent}
                  </span>
                )}
                {call.handledBy.kind === "handoff" && (
                  <span className="inline-flex items-center gap-050 text-text-subtle">
                    <ArrowLeftRight className="h-3.5 w-3.5" /> {call.handledBy.bot} → {call.handledBy.agent}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-050">
              <Button asChild variant="outline" size="sm" className="h-400 gap-050 text-body-small">
                <Link to="/customers/$customerId" params={{ customerId: call.customerId }}>
                  Customer 360
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </Button>
              <Button variant="ghost" size="icon" className="h-400 w-400" onClick={onClose}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Player + sentiment */}
        <div className="shrink-0 space-y-150 border-b border-border bg-surface-sunken px-250 py-150">
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
          <TabsList className="mx-250 mt-150 shrink-0 self-start">
            <TabsTrigger value="transcript">Transcript</TabsTrigger>
            <TabsTrigger value="summary">Summary</TabsTrigger>
            <TabsTrigger value="disclosures">
              Disclosures
              <Lozenge tone="neutral" className="ml-075 font-mono">
                {disclosuresRead}/{call.disclosures.length}
              </Lozenge>
            </TabsTrigger>
            <TabsTrigger value="trace">Trace</TabsTrigger>
            <TabsTrigger value="cost">Cost</TabsTrigger>
            <TabsTrigger value="meta">Metadata</TabsTrigger>
          </TabsList>

          <div className="min-h-0 flex-1 overflow-y-auto px-250 py-150">
            <TabsContent value="transcript" className="mt-0">
              <TranscriptView turns={call.transcript} currentTime={currentTime} onSeek={setCurrentTime} />
            </TabsContent>

            {/* Per-turn timeline: which tools ran, what was retrieved and where
                the latency went. Until now this was three unjoinable tables. */}
            <TabsContent value="trace" className="mt-0">
              <TurnTraceView interactionId={call.id} />
            </TabsContent>

            {/* Measured spend for this one call, split by service and model.
                Replaces having no per-call figure at all — the billing KPI was
                total spend divided by call count. */}
            <TabsContent value="cost" className="mt-0">
              <CallCostPanel interactionId={call.id} />
            </TabsContent>

            <TabsContent value="summary" className="mt-0 space-y-150">
              <div className="rounded-medium border border-border bg-surface p-150 text-body leading-relaxed text-text">
                {call.summary}
              </div>
              <div>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Tags</div>
                <div className="flex flex-wrap gap-075">
                  {call.tags.length === 0 ? (
                    <span className="text-body-small text-text-subtlest">No tags.</span>
                  ) : (
                    call.tags.map((t) => (
                      <Lozenge key={t} tone="selected">
                        #{t}
                      </Lozenge>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="mb-050 text-body-small font-semibold text-text-subtlest">Flags</div>
                <div className="flex flex-wrap gap-075">
                  {call.flags.length === 0 ? (
                    <span className="text-body-small text-text-success">Clean call — no flags.</span>
                  ) : (
                    call.flags.map((f) => (
                      <Lozenge key={f} tone="danger">
                        {f}
                      </Lozenge>
                    ))
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="disclosures" className="mt-0">
              <ul className="divide-y divide-border rounded-medium border border-border bg-surface">
                {call.disclosures.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-150 px-150 py-100">
                    <div className="flex items-center gap-100">
                      {d.read ? (
                        <ShieldCheck className="h-4 w-4 text-text-success" />
                      ) : (
                        <ShieldX className="h-4 w-4 text-text-danger" />
                      )}
                      <span className="text-body text-text">{d.label}</span>
                    </div>
                    <div className="text-body-small">
                      {d.read ? (
                        <span className="font-mono text-text-subtle">at {formatDuration(d.atSec ?? 0)}</span>
                      ) : (
                        <span className="font-medium text-text-danger">Missed</span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              {call.disclosures.some((d) => !d.read) && (
                <div className="mt-100 rounded-medium bg-[var(--danger-bg)] px-150 py-100 text-body-small text-text-danger">
                  Missed disclosures on this call may fail compliance review.
                </div>
              )}
            </TabsContent>

            <TabsContent value="meta" className="mt-0">
              <dl className="grid grid-cols-2 gap-x-300 gap-y-100 text-body">
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
    <div className={cn("border-b border-border pb-075", full && "col-span-2")}>
      <dt className="text-body-small text-text-subtlest">{k}</dt>
      <dd className={cn("text-text", mono && "font-mono text-body-small")}>{v}</dd>
    </div>
  );
}
