import { ExternalLink } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { chunkTitle, type SandboxTurn } from "@/data/sandbox-seed";

export function RetrievalTab({ turns }: { turns: SandboxTurn[] }) {
  const lastBot = [...turns].reverse().find((t) => t.role === "bot");
  if (!lastBot) {
    return <Empty text="Send a message to see what the bot retrieved." />;
  }
  const ids = lastBot.chunkIds ?? [];
  if (ids.length === 0) {
    return <Empty text="No chunks retrieved for this turn." />;
  }
  const chunks = ids.map((id, i) => ({ id, score: 0.92 - i * 0.08, ...chunkTitle(id) }));
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[11px] text-text-muted">
        <span>Top {chunks.length} chunks · {lastBot.latencyMs}ms · {lastBot.tokens}t</span>
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

function Empty({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed border-[var(--border-token)] p-6 text-center text-[12px] text-text-muted">{text}</div>;
}
