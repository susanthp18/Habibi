"use client";

// AgentStudio: ask the knowledge base a question the way an agent would and
// see which passages come back, how close they are, and from which document,
// before a customer hears the answer.
import { Loader2, Search } from "lucide-react";
import { type FormEvent, useState } from "react";

import { searchChunksApiV1KnowledgeBaseSearchPost } from "@/agentstudio/client/sdk.gen";
import type { ChunkResponseSchema } from "@/agentstudio/client/types.gen";
import { Button } from "@/agentstudio/components/ui/button";
import { Input } from "@/agentstudio/components/ui/input";
import { Label } from "@/agentstudio/components/ui/label";
import { detailFromError } from "@/agentstudio/lib/apiError";

const RESULTS = 5;

export default function TestRetrieval() {
    const [query, setQuery] = useState("");
    const [chunks, setChunks] = useState<ChunkResponseSchema[] | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const search = async (event: FormEvent) => {
        event.preventDefault();
        if (!query.trim()) return;
        setLoading(true);
        setError(null);
        const response = await searchChunksApiV1KnowledgeBaseSearchPost({
            body: { query: query.trim(), limit: RESULTS },
        });
        setLoading(false);
        if (response.error) {
            setError(detailFromError(response.error, "Search failed"));
            setChunks(null);
            return;
        }
        setChunks(response.data?.chunks ?? []);
    };

    return (
        <div className="space-y-4">
            <form onSubmit={search} className="flex items-end gap-2">
                <div className="flex-1 space-y-1">
                    <Label htmlFor="kb-test-query">Question</Label>
                    <Input
                        id="kb-test-query"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="e.g. What happens if I miss my EMI date?"
                    />
                </div>
                <Button type="submit" disabled={loading || !query.trim()}>
                    {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                    Search
                </Button>
            </form>
            {error && (
                <p role="alert" className="text-sm text-destructive">
                    {error}
                </p>
            )}
            {chunks && chunks.length === 0 && (
                <p className="text-sm text-muted-foreground">
                    Nothing in the knowledge base matches. An agent asked this would have no source to answer from.
                </p>
            )}
            {chunks && chunks.length > 0 && (
                <ol className="space-y-3">
                    {chunks.map((c) => (
                        <li key={c.id} className="rounded-md border p-3">
                            <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                                <span className="truncate">
                                    {c.filename} · passage {c.chunk_index + 1}
                                </span>
                                <span>{Math.round(c.similarity * 100)}% match</span>
                            </div>
                            <p className="whitespace-pre-wrap text-sm">{c.chunk_text}</p>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}
