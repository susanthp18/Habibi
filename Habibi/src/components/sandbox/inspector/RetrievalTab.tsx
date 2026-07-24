import { ExternalLink } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { groundedLabel } from "@/api/sandbox";
import { chunkTitle, type SandboxTurn } from "@/data/sandbox-seed";
import type { LiveRagHit } from "@/components/sandbox/voice/liveEvents";

export function RetrievalTab({
  turns,
  ragHits = [],
}: {
  turns: SandboxTurn[];
  ragHits?: LiveRagHit[];
}) {
  // A live voice call has no per-turn `chunks` on the transcript — retrieval is
  // reported out-of-band over RTVI. When those events exist they are the truth.
  if (ragHits.length > 0) {
    return <LiveRetrieval hits={ragHits} />;
  }

  const lastBot = [...turns].reverse().find((t) => t.role === "bot");
  if (!lastBot) {
    return <Empty text="Send a message to see what the bot retrieved." />;
  }

  const live = lastBot.chunks ?? [];
  if (live.length > 0) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between text-[11px] text-text-muted">
          <span>
            Top {live.length} chunks · {lastBot.latencyMs}ms · {lastBot.tokens}t
          </span>
          <Link
            to="/knowledge-base"
            className="inline-flex items-center gap-1 hover:text-text-secondary"
          >
            Open KB <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
        {live.map((c) => (
          <div
            key={c.chunkId}
            className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5"
          >
            <div className="flex items-center gap-2 text-[11px] text-text-muted">
              <span className="font-mono">{c.chunkId}</span>
              {typeof c.score === "number" && (
                <span className="ml-auto font-mono">{c.score.toFixed(2)}</span>
              )}
            </div>
            {typeof c.score === "number" && (
              <div className="mt-1 h-1 w-full overflow-hidden rounded bg-surface-card">
                <div className="h-full bg-brand-primary" style={{ width: `${c.score * 100}%` }} />
              </div>
            )}
            <div className="mt-1.5 text-[12px] font-medium text-text-primary">
              {c.heading || groundedLabel(c)}
            </div>
            <div className="text-[10.5px] text-text-muted">{groundedLabel(c)}</div>
            {c.snippet && (
              <div className="mt-1 line-clamp-3 text-[11.5px] text-text-secondary">{c.snippet}</div>
            )}
          </div>
        ))}
      </div>
    );
  }

  const ids = lastBot.chunkIds ?? [];
  if (ids.length === 0) {
    return <Empty text="No chunks retrieved for this turn." />;
  }
  const chunks = ids.map((id, i) => ({ id, score: 0.92 - i * 0.08, ...chunkTitle(id) }));
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        <span>
          Top {chunks.length} chunks · {lastBot.latencyMs}ms · {lastBot.tokens}t
        </span>
        <Link to="/knowledge-base" className="inline-flex items-center gap-1 hover:text-text-secondary">
          Open KB <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {chunks.map((c) => (
        <div key={c.id} className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5">
          <div className="flex items-center gap-2 text-[11px] text-text-muted">
            <span className="font-mono">{c.id}</span>
            <span className="ml-auto font-mono">{c.score.toFixed(2)}</span>
          </div>
          <div className="mt-1 h-1 w-full overflow-hidden rounded bg-surface-card">
            <div className="h-full bg-brand-primary" style={{ width: `${c.score * 100}%` }} />
          </div>
          <div className="mt-1.5 text-[12px] font-medium text-text-primary">{c.heading}</div>
          <div className="text-[10.5px] text-text-muted">{c.doc}</div>
          <div className="mt-1 line-clamp-3 text-[11.5px] text-text-secondary">{c.snippet}</div>
        </div>
      ))}
    </div>
  );
}

/**
 * Live-call retrieval, newest first. Shows the pinned snapshot explicitly:
 * a narrow snapshot legitimately returns zero hits, and without this the
 * operator cannot tell that from a broken KB.
 */
function LiveRetrieval({ hits }: { hits: LiveRagHit[] }) {
  const ordered = [...hits].reverse();
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        <span>
          {hits.length} retrieval {hits.length === 1 ? "call" : "calls"} this session
        </span>
        <Link to="/knowledge-base" className="inline-flex items-center gap-1 hover:text-text-secondary">
          Open KB <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {ordered.map((h) => (
        <div
          key={h.id}
          className="rounded-md border border-[var(--border-token)] bg-surface-sunken p-2.5"
        >
          <div className="flex items-center gap-2 text-[11px] text-text-muted">
            <span className="rounded bg-surface-card px-1.5 py-0.5 text-[10px] font-medium">
              {h.source}
            </span>
            {typeof h.topScore === "number" && (
              <span className="ml-auto font-mono">{h.topScore.toFixed(2)}</span>
            )}
          </div>
          <div className="mt-1.5 text-[12px] font-medium text-text-primary">{h.query}</div>
          <div className="mt-1 text-[10.5px] text-text-muted">
            {h.chunkIds.filter(Boolean).length > 0
              ? h.chunkIds.filter(Boolean).join(" · ")
              : "no chunks above threshold"}
          </div>
          {h.snapshotId && (
            <div className="mt-1 font-mono text-[10px] text-text-muted">
              snapshot: {h.snapshotId}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">
      {text}
    </div>
  );
}
