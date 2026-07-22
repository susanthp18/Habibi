import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { toast } from "sonner";
import { runMockRetrieval, type RetrievalResult } from "@/data/kb-seed";
import { Search, Sparkles, Copy, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

const SAMPLES = [
  "What is the late fee if I pay 10 days late?",
  "Can I foreclose my loan without any charges?",
  "How do I get a top-up loan?",
  "My call keeps switching back to English from Tamil",
];

function scoreColor(s: number) {
  if (s >= 0.8) return "bg-emerald-500";
  if (s >= 0.5) return "bg-brand-primary";
  return "bg-text-muted";
}

function highlight(text: string, terms: string[]) {
  if (terms.length === 0) return text;
  const re = new RegExp(`\\b(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\b`, "gi");
  const parts = text.split(re);
  return parts.map((p, i) =>
    re.test(p) ? (
      <mark key={i} className="rounded bg-amber-100 px-0.5 text-brand-navy">
        {p}
      </mark>
    ) : (
      <span key={i}>{p}</span>
    ),
  );
}

export function TestRetrievalPanel() {
  const [query, setQuery] = useState("What is the current late fee amount?");
  const [topK, setTopK] = useState(4);
  const [results, setResults] = useState<RetrievalResult[]>([]);
  const [latency, setLatency] = useState(0);
  const [ran, setRan] = useState(false);

  const run = () => {
    const { results: r, latencyMs } = runMockRetrieval(query, topK);
    setResults(r);
    setLatency(latencyMs);
    setRan(true);
  };

  const copyPayload = () => {
    const payload = { query, topK, contexts: results.map((r) => ({ doc: r.docTitle, score: r.score.toFixed(3), snippet: r.snippet })) };
    navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    toast.success("Prompt payload copied to clipboard");
  };

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-3 rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Test retrieval</div>
          <div className="text-[11px] text-text-muted">
            Run a mock query against enabled sources — see what the bot would pull as context.
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Query
          </label>
          <div className="flex gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run()}
              placeholder="Ask the bot…"
            />
            <Button onClick={run} size="sm">
              <Search className="mr-1 h-3.5 w-3.5" /> Run
            </Button>
          </div>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px] font-medium uppercase tracking-wide text-text-muted">
            <span>Top-K</span>
            <span className="font-mono normal-case tracking-normal text-brand-navy">{topK}</span>
          </div>
          <Slider min={1} max={8} step={1} value={[topK]} onValueChange={(v) => setTopK(v[0])} />
        </div>
        <div>
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Try one
          </div>
          <div className="flex flex-wrap gap-1.5">
            {SAMPLES.map((s) => (
              <button
                key={s}
                onClick={() => setQuery(s)}
                className="rounded-full border border-[var(--border-token)] bg-surface-app px-2 py-1 text-[11px] text-text-secondary hover:border-brand-primary/40 hover:text-brand-primary-dark"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {ran && (
          <div className="flex items-center justify-between border-t border-[var(--border-token)] pt-3 text-[11px] text-text-muted">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" /> {latency} ms · {results.length} hits
            </span>
            <Button size="sm" variant="ghost" onClick={copyPayload} disabled={results.length === 0}>
              <Copy className="mr-1 h-3 w-3" /> Copy payload
            </Button>
          </div>
        )}
      </div>

      <div className="min-h-0 space-y-2">
        {!ran ? (
          <div className="flex h-full min-h-[300px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border-token)] p-10 text-center">
            <Sparkles className="h-6 w-6 text-brand-primary" />
            <div className="text-[13px] font-medium text-brand-navy">
              Type a query and hit Run
            </div>
            <div className="max-w-sm text-[11px] text-text-muted">
              Results are ranked by mock cosine similarity across enabled documents + FAQs.
            </div>
          </div>
        ) : results.length === 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-[12px] text-amber-800">
            No enabled source matched this query. Consider adding a KB doc or FAQ pair.
          </div>
        ) : (
          results.map((r, i) => (
            <div
              key={r.chunkId}
              className="rounded-lg border border-[var(--border-token)] bg-surface-card p-3"
            >
              <div className="flex items-center justify-between text-[11px] text-text-muted">
                <div className="flex items-center gap-2">
                  <span className="rounded-md bg-surface-sunken px-1.5 py-0.5 font-mono text-brand-navy">
                    #{i + 1}
                  </span>
                  <span className="font-medium text-text-secondary">{r.docTitle}</span>
                  <span>·</span>
                  <span>{r.heading}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                    <div
                      className={cn("h-full", scoreColor(r.score))}
                      style={{ width: `${Math.round(r.score * 100)}%` }}
                    />
                  </div>
                  <span className="font-mono tabular-nums text-brand-navy">{r.score.toFixed(2)}</span>
                </div>
              </div>
              <div className="mt-1.5 text-[13px] leading-relaxed text-text-primary">
                {highlight(r.snippet, r.matchedTerms)}
              </div>
              {r.matchedTerms.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {r.matchedTerms.map((t) => (
                    <span key={t} className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-800">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
