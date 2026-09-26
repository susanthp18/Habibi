"use client";

// AgentStudio: one line above any conversation (live test, text tester, run
// page): how fast the agent answered across the call, and the transcript as a
// file for review or a bug report.
import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";

import type { ConversationItem } from "./types";

export function latencySummary(items: ConversationItem[]) {
    const times = items
        .map((item) => item.reasoningDurationMs)
        .filter((ms): ms is number => typeof ms === "number" && Number.isFinite(ms));
    if (times.length === 0) return null;
    const sorted = [...times].sort((a, b) => a - b);
    return {
        count: times.length,
        averageMs: Math.round(times.reduce((sum, ms) => sum + ms, 0) / times.length),
        slowestMs: Math.round(sorted[sorted.length - 1]!),
    };
}

type TranscriptEntry = Record<string, unknown>;

export function transcriptOf(items: ConversationItem[]): TranscriptEntry[] {
    return items.flatMap((item): TranscriptEntry[] => {
        if (item.kind === "message") {
            return [{ at: item.timestamp, speaker: item.role === "user" ? "customer" : "agent", text: item.text }];
        }
        if (item.kind === "tool-call") {
            return [{ at: item.timestamp, speaker: "tool", name: item.functionName, arguments: item.arguments, result: item.result }];
        }
        if (item.kind === "node-transition") {
            return [{ at: item.timestamp, speaker: "flow", step: item.nodeName }];
        }
        return [{ at: item.timestamp, speaker: "notice", title: item.title, text: item.text }];
    });
}

export function ConversationSummary({ items, fileName }: { items: ConversationItem[]; fileName: string }) {
    if (items.length === 0) return null;
    const latency = latencySummary(items);
    const download = () => {
        const blob = new Blob([JSON.stringify(transcriptOf(items), null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${fileName}.json`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    };
    return (
        <div className="flex items-center justify-between gap-2 border-b px-4 py-2 text-xs text-muted-foreground">
            <span>
                {latency
                    ? `Response time: average ${latency.averageMs} ms, slowest ${latency.slowestMs} ms over ${latency.count} replies`
                    : "No response times recorded"}
            </span>
            <Button type="button" variant="ghost" size="sm" onClick={download}>
                <Download className="mr-1 h-3 w-3" />
                Transcript
            </Button>
        </div>
    );
}
