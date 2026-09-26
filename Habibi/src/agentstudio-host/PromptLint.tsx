/**
 * Host slot "@/host/PromptLint": under every node prompt in the agent editor,
 * what the engine will actually render (unsupplied context keys that become
 * blank, old single-brace variables that are spoken literally, prohibited
 * phrases, a missing recording disclosure on the opening) and what the prompt
 * costs on each model turn it is active.
 */
import { useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { usePromptLint } from "@/api/voice-studio";
import { cn } from "@/lib/utils";

const DEBOUNCE_MS = 700;

const TONE = {
  error: "text-text-danger",
  warn: "text-text-warning",
  info: "text-text-subtle",
} as const;

export default function PromptLint({
  prompt,
  isOpening,
  spokenFirst = "",
}: {
  prompt: string;
  isOpening: boolean;
  /** What is said before the prompt takes over (the opening's greeting text). */
  spokenFirst?: string;
}) {
  const params: { workflowId?: string } = useParams({ strict: false });
  const workflowId = params.workflowId ? Number(params.workflowId) : null;
  const [settled, setSettled] = useState({ prompt, spokenFirst });
  useEffect(() => {
    const t = setTimeout(() => setSettled({ prompt, spokenFirst }), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [prompt, spokenFirst]);
  const lint = usePromptLint(settled.prompt, workflowId, isOpening, settled.spokenFirst);

  if (!prompt.trim()) return null;
  if (lint.isError) {
    return <p className="text-body-small text-text-subtle">Prompt checks unavailable right now.</p>;
  }
  const result = lint.data;
  if (!result) return null;
  return (
    <div className="space-y-050" aria-live="polite">
      <p className="text-body-small text-text-subtle">
        {result.tokens.toLocaleString()} tokens · about ${(result.usdPerTurn * 1000).toFixed(3)} per
        1,000 model turns
      </p>
      {result.findings.length > 0 && (
        <ul className="space-y-050">
          {result.findings.map((f, i) => (
            <li key={`${f.code}-${i}`} className={cn("text-body-small", TONE[f.severity])}>
              {f.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
