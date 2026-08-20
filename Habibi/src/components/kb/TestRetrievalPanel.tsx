import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { toast } from "sonner";
import { retrieveKb, type RetrievalResult } from "@/api/kb";
import { Search, Sparkles, Copy, Clock, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Lozenge } from "@/components/ui/lozenge";

const SAMPLES = [
  "What is NCD protector for car insurance?",
  "Is windscreen cover unlimited on Car Protect360?",
  "What happens if my maid is hospitalized?",
  "Does travel insurance cover COVID quarantine?",
];

function scoreColor(s: number) {
  if (s >= 0.8) return "bg-background-success-bold";
  if (s >= 0.5) return "bg-background-brand-bold";
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
      <mark key={`m-${key++}`} className="rounded bg-background-warning-subtler px-025 text-text">
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
    // Await the write: the success toast used to fire before (and regardless
    // of) the clipboard result, and a rejected writeText — denied permission,
    // non-secure context — became an unhandled rejection.
    const write = navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    if (!write) {
      toast.error("Clipboard is not available in this browser");
      return;
    }
    write.then(
      () => toast.success("Prompt payload copied to clipboard"),
      () => toast.error("Could not copy to clipboard"),
    );
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 overflow-hidden lg:grid-cols-[20rem_minmax(0,1fr)]">
      <div className="min-h-0 space-y-150 overflow-y-auto border-b border-border p-200 lg:border-b-0 lg:border-r">
        <div>
          <div className="text-body-small text-text-subtlest">
            Run a live vector query against indexed HDFC policies, benefits and FAQs.
          </div>
        </div>
        <div>
          <label className="mb-050 block text-body-small font-medium text-text-subtlest">
            Query
          </label>
          <div className="flex gap-100">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void run()}
              placeholder="Ask about coverage, NCD, claims…"
              disabled={loading}
            />
            <Button onClick={() => void run()} size="sm" disabled={loading || !query.trim()}>
              {loading ? <Loader2 className="mr-050 h-3.5 w-3.5 animate-spin" /> : <Search className="mr-050 h-3.5 w-3.5" />}
              Run
            </Button>
          </div>
        </div>
        <div>
          <div className="mb-050 flex items-center justify-between text-body-small font-medium text-text-subtlest">
            <span>Top-K</span>
            <span className="font-mono normal-case tracking-normal text-text">{topK}</span>
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
        <label className="flex items-center gap-100 text-body-small text-text-subtle">
          <input
            type="checkbox"
            className="rounded border-border"
            checked={includeDraft}
            onChange={(e) => setIncludeDraft(e.target.checked)}
            disabled={loading}
          />
          Generate drafted answer (Azure chat)
        </label>
        <div>
          <div className="mb-075 text-body-small font-medium text-text-subtlest">
            Try one
          </div>
          <div className="flex flex-wrap gap-075">
            {SAMPLES.map((s) => (
              <button
                key={s}
                onClick={() => setQuery(s)}
                disabled={loading}
                className="rounded-full border border-border bg-surface px-100 py-050 text-body-small text-text-subtle hover:border-border-brand/40 hover:text-text-brand disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
        {ran && (
          <div className="space-y-050 border-t border-border pt-150 text-body-small text-text-subtlest">
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-050">
                <Clock className="h-3 w-3" /> {latency} ms · {results.length} hits
              </span>
              <Button size="sm" variant="ghost" onClick={copyPayload} disabled={results.length === 0}>
                <Copy className="mr-050 h-3 w-3" /> Copy payload
              </Button>
            </div>
            {meta.embeddingModel && (
              <div className="font-mono text-body-small">
                embed={meta.embeddingModel}
                {meta.chatModel ? ` · chat=${meta.chatModel}` : ""}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="min-h-0 overflow-y-auto p-200">
        {!ran ? (
          <div className="flex h-full min-h-[18.75rem] flex-col items-center justify-center gap-100 rounded-large border border-dashed border-border p-500 text-center">
            <Sparkles className="h-300 w-300 text-text-brand" />
            <div className="text-body font-medium text-text">
              Type a query and hit Run
            </div>
            <div className="max-w-sm text-body-small text-text-subtlest">
              Results are ranked by Azure embedding cosine similarity across enabled documents + FAQs.
            </div>
          </div>
        ) : (
          <div className="space-y-100">
            {draftAnswer && (
              <div className="rounded-large border border-border-brand/30 bg-background-brand-subtlest/40 p-150">
                <div className="mb-050 text-body-small font-semibold text-text-brand">
                  Drafted answer
                </div>
                <div className="whitespace-pre-wrap text-body leading-relaxed text-text">
                  {draftAnswer}
                </div>
              </div>
            )}
            {results.length === 0 ? (
              <div className="rounded-large border border-border-warning-subtle bg-background-warning-subtler p-200 text-body-small text-text-warning-bolder">
                No enabled source matched this query. Consider adding a KB doc or FAQ pair.
              </div>
            ) : (
              results.map((r, i) => (
                <div
                  key={r.chunkId}
                  className="rounded-large border border-border bg-surface p-150"
                >
                  <div className="flex items-center justify-between text-body-small text-text-subtlest">
                    <div className="flex min-w-0 items-center gap-100">
                      <span className="rounded-medium bg-surface-sunken px-075 py-025 font-mono text-text">
                        #{i + 1}
                      </span>
                      <span className="truncate font-medium text-text-subtle">{r.docTitle}</span>
                      <span>·</span>
                      <span className="truncate">{r.heading}</span>
                    </div>
                    <div className="ml-100 flex shrink-0 items-center gap-100">
                      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken">
                        <div
                          className={cn("h-full", scoreColor(r.score))}
                          style={{ width: `${Math.round(r.score * 100)}%` }}
                        />
                      </div>
                      <span className="font-mono tabular-nums text-text">{r.score.toFixed(2)}</span>
                    </div>
                  </div>
                  <div className="mt-075 text-body leading-relaxed text-text">
                    {highlight(r.snippet, r.matchedTerms)}
                  </div>
                  {r.matchedTerms.length > 0 && (
                    <div className="mt-100 flex flex-wrap gap-050">
                      {r.matchedTerms.map((t) => (
                        <Lozenge key={t} tone="warning">
                          {t}
                        </Lozenge>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
