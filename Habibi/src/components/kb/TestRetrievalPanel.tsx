import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { toast } from "sonner";
import { retrieveKb, type RetrievalResult } from "@/api/kb";
import { Search, Sparkles, Copy, Clock, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const SAMPLES = [
  "What is NCD protector for car insurance?",
  "Is windscreen cover unlimited on Car Protect360?",
  "What happens if my maid is hospitalized?",
  "Does travel insurance cover COVID quarantine?",
];

function scoreColor(s: number) {
  if (s >= 0.8) return "bg-emerald-500";
  if (s >= 0.5) return "bg-brand-primary";
  return "bg-text-muted";
}

function highlight(text: string, terms: string[]) {
  if (terms.length === 0) return text;
  const escaped = terms
    .map((t) => t.trim())
    .filter(Boolean)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!escaped.length) return text;
  const re = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(<span key={`t-${key++}`}>{text.slice(last, match.index)}</span>);
    }
    nodes.push(
      <mark key={`m-${key++}`} className="rounded bg-amber-100 px-0.5 text-brand-navy">
        {match[0]}
      </mark>,
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(<span key={`t-${key++}`}>{text.slice(last)}</span>);
  return nodes.length ? nodes : text;
}

export function TestRetrievalPanel() {
  const [query, setQuery] = useState("What is NCD protector for car insurance?");
  const [topK, setTopK] = useState(4);
  const [includeDraft, setIncludeDraft] = useState(true);
  const [results, setResults] = useState<RetrievalResult[]>([]);
  const [draftAnswer, setDraftAnswer] = useState<string | null>(null);
  const [latency, setLatency] = useState(0);
  const [meta, setMeta] = useState<{ embeddingModel?: string; chatModel?: string | null }>({});
  const [ran, setRan] = useState(false);
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    try {
      const res = await retrieveKb({
        query: query.trim(),
        topK,
        includeDraftAnswer: includeDraft,
        source: "test",
      });
      setResults(res.results);
      setDraftAnswer(res.draftAnswer);
      setLatency(res.latencyMs);
      setMeta({ embeddingModel: res.embeddingModel, chatModel: res.chatModel });
      setRan(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Retrieval failed";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  const copyPayload = () => {
    const payload = {
      query,
      topK,
      draftAnswer,
      contexts: results.map((r) => ({
        doc: r.docTitle,
        score: r.score.toFixed(3),
        snippet: r.snippet,
      })),
    };
    navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    toast.success("Prompt payload copied to clipboard");
  };

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-3 rounded-lg border border-[var(--border-token)] bg-surface-card p-4">
        <div>
          <div className="text-[13px] font-semibold text-brand-navy">Test retrieval</div>
          <div className="text-[11px] text-text-muted">
            Run a live vector query against indexed HDFC policies, benefits and FAQs.
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
              onKeyDown={(e) => e.key === "Enter" && void run()}
              placeholder="Ask about coverage, NCD, claims…"
              disabled={loading}
            />
            <Button onClick={() => void run()} size="sm" disabled={loading || !query.trim()}>
              {loading ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Search className="mr-1 h-3.5 w-3.5" />}
              Run
            </Button>
          </div>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px] font-medium uppercase tracking-wide text-text-muted">
            <span>Top-K</span>
            <span className="font-mono normal-case tracking-normal text-brand-navy">{topK}</span>
          </div>
          <Slider
            min={1}
            max={8}
            step={1}
            value={[topK]}
            onValueChange={(v) => setTopK(v[0])}
            disabled={loading}
          />
        </div>
        <label className="flex items-center gap-2 text-[12px] text-text-secondary">
          <input
            type="checkbox"
            className="rounded border-[var(--border-token)]"
            checked={includeDraft}
            onChange={(e) => setIncludeDraft(e.target.checked)}
            disabled={loading}
          />
          Generate drafted answer (Azure chat)
        </label>
        <div>
          <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Try one
          </div>
          <div className="flex flex-wrap gap-1.5">
            {SAMPLES.map((s) => (
              <button
                key={s}
                onClick={() => setQuery(s)}
                disabled={loading}
                className="rounded-full border border-[var(--border-token)] bg-surface-app px-2 py-1 text-[11px] text-text-secondary hover:border-brand-primary/40 hover:text-brand-primary-dark disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {ran && (
          <div className="space-y-1 border-t border-[var(--border-token)] pt-3 text-[11px] text-text-muted">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" /> {latency} ms · {results.length} hits
              </span>
              <Button size="sm" variant="ghost" onClick={copyPayload} disabled={results.length === 0}>
                <Copy className="mr-1 h-3 w-3" /> Copy payload
              </Button>
            </div>
            {meta.embeddingModel && (
              <div className="font-mono text-[10px]">
                embed={meta.embeddingModel}
                {meta.chatModel ? ` · chat=${meta.chatModel}` : ""}
              </div>
            )}
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
              Results are ranked by Azure embedding cosine similarity across enabled documents + FAQs.
            </div>
          </div>
        ) : (
          <>
            {draftAnswer && (
              <div className="rounded-lg border border-brand-primary/30 bg-brand-tint/40 p-3">
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-brand-primary-dark">
                  Drafted answer
                </div>
                <div className="whitespace-pre-wrap text-[13px] leading-relaxed text-brand-navy">
                  {draftAnswer}
                </div>
              </div>
            )}
            {results.length === 0 ? (
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
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="rounded-md bg-surface-sunken px-1.5 py-0.5 font-mono text-brand-navy">
                        #{i + 1}
                      </span>
                      <span className="truncate font-medium text-text-secondary">{r.docTitle}</span>
                      <span>·</span>
                      <span className="truncate">{r.heading}</span>
                    </div>
                    <div className="ml-2 flex shrink-0 items-center gap-2">
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
          </>
        )}
      </div>
    </div>
  );
}
