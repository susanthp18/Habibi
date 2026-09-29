// -----------------------------------------------------------------------------
// Call recordings: one fetch path for every player (Audit, Redaction).
//   GET /interactions/{id}/recording?variant=auto|original|redacted
//   GET /interactions/{id}/recording/peaks
// The unredacted recording needs raw-PII permission; everyone else hears the
// redacted copy (each finding beeped). `auto` asks for the best the viewer may
// hear, and the server says which one it sent.
// -----------------------------------------------------------------------------

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ApiError, apiGet, apiGetBlob } from "./config";

export type RecordingVariant = "auto" | "original" | "redacted";

export type RecordingState =
  | { kind: "loading" }
  | { kind: "ready"; src: string; variant: "original" | "redacted" }
  /** The call has audio, but its redacted copy is still being made. */
  | { kind: "pending" }
  | { kind: "none" }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

export function useRecording(interactionId: string, variant: RecordingVariant = "auto") {
  const [state, setState] = useState<RecordingState>({ kind: "loading" });
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    // Callers mount before they know the call (the Audit drawer, a run whose
    // interaction is still loading): no id, no request.
    if (!interactionId) {
      setState({ kind: "none" });
      return;
    }
    setState({ kind: "loading" });
    apiGetBlob(`/interactions/${encodeURIComponent(interactionId)}/recording?variant=${variant}`)
      .then(({ blob, headers }) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        const sent = headers.get("X-Recording-Variant") === "original" ? "original" : "redacted";
        setState({ kind: "ready", src: objectUrl, variant: sent });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.status === 404) return setState({ kind: "none" });
          if (err.status === 409) return setState({ kind: "pending" });
          if (err.status === 403) return setState({ kind: "forbidden" });
        }
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [interactionId, variant]);
  return state;
}

export interface RecordingPeaks {
  durationSec: number;
  /** "customer" and "agent" for stereo; "mixed" for mono. Values 0..1. */
  channels: Record<string, number[]>;
}

export function useRecordingPeaks(interactionId: string, enabled = true) {
  return useQuery({
    queryKey: ["recording-peaks", interactionId],
    queryFn: () =>
      apiGet<RecordingPeaks>(
        `/interactions/${encodeURIComponent(interactionId)}/recording/peaks?bins=240`,
      ),
    enabled,
    staleTime: Infinity, // a filed recording never changes
    retry: false,
  });
}
