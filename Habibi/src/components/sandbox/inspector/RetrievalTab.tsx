import { ExternalLink } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { groundedLabel } from "@/api/sandbox";
import { chunkTitle, type SandboxTurn } from "@/data/sandbox-seed";
import type { LiveRagHit } from "@/components/sandbox/voice/liveEvents";

function scoreBarWidth(score: number): string {
  return `${Math.min(100, Math.max(0, score * 100))}%`;
}

function ChunkCard({
  chunkId,
  score,
  heading,
  docLabel,
  snippet,
}: {
  chunkId: string;
  score?: number | null;
  heading: string;
  docLabel: string;
  snippet?: string | null;
}) {
  return (
    <div className="rounded-medium border border-border bg-surface-sunken p-150">
      <div className="flex items-center gap-100 text-body-small text-text-subtlest">
        <span className="font-mono">{chunkId}</span>
        {typeof score === "number" && <span className="ml-auto font-mono">{score.toFixed(2)}</span>}
      </div>
      {typeof score === "number" && (
        <div className="mt-050 h-050 w-full overflow-hidden rounded bg-surface">
          <div
            className="h-full bg-background-brand-bold"
            style={{ width: scoreBarWidth(score) }}
          />
        </div>
      )}
      <div className="mt-075 text-body-small font-medium text-text">{heading}</div>
      <div className="text-body-small text-text-subtlest">{docLabel}</div>
      {snippet && (
        <div className="mt-050 line-clamp-3 text-body-small text-text-subtle">{snippet}</div>
      )}
    </div>
  );
}

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
      <div className="space-y-150">
        <div className="flex items-center justify-between text-body-small text-text-subtlest">
          <span>
            Top {live.length} chunks · {lastBot.latencyMs}ms · {lastBot.tokens}t
          </span>
          <Link
            to="/knowledge-base"
            search={{ tab: "test" }}
            className="inline-flex items-center gap-050 hover:text-text-subtle"
          >
            Open KB <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
        {live.map((c) => (
          <ChunkCard
            key={c.chunkId}
            chunkId={c.chunkId}
            score={c.score}
            heading={c.heading || groundedLabel(c)}
            docLabel={groundedLabel(c)}
            snippet={c.snippet}
          />
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
    <div className="space-y-150">
      <div className="flex items-center justify-between text-body-small text-text-subtlest">
        <span>
          Top {chunks.length} chunks · {lastBot.latencyMs}ms · {lastBot.tokens}t
        </span>
        <Link
          to="/knowledge-base"
          search={{ tab: "test" }}
          className="inline-flex items-center gap-050 hover:text-text-subtle"
        >
          Open KB <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {chunks.map((c) =>
        c ? (
          <ChunkCard
            key={c.id}
            chunkId={c.id}
            score={c.score}
            heading={c.heading || c.id}
            docLabel={c.doc || c.id}
            snippet={c.snippet}
          />
        ) : null,
      )}
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
    <div className="space-y-100">
      <div className="flex items-center justify-between text-body-small text-text-subtlest">
        <span>
          {hits.length} retrieval {hits.length === 1 ? "call" : "calls"} this session
        </span>
        <Link
          to="/knowledge-base"
          search={{ tab: "test" }}
          className="inline-flex items-center gap-050 hover:text-text-subtle"
        >
          Open KB <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
      {ordered.map((h) => (
        <div key={h.id} className="rounded-medium border border-border bg-surface-sunken p-150">
          <div className="flex items-center gap-100 text-body-small text-text-subtlest">
            <span className="rounded bg-surface px-075 py-025 text-body-small font-medium">
              {h.source}
            </span>
            {typeof h.topScore === "number" && (
              <span className="ml-auto font-mono">{h.topScore.toFixed(2)}</span>
            )}
          </div>
          <div className="mt-075 text-body-small font-medium text-text">{h.query}</div>
          <div className="mt-050 text-body-small text-text-subtlest">
            {h.chunkIds.filter(Boolean).length > 0
              ? h.chunkIds.filter(Boolean).join(" · ")
              : "no chunks above threshold"}
          </div>
          {h.snapshotId && (
            <div className="mt-050 font-mono text-body-small text-text-subtlest">
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
    <div className="rounded-medium border border-dashed border-border p-300 text-center text-body-small text-text-subtlest">
      {text}
    </div>
  );
}
