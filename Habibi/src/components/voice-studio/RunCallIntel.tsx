import { Link } from "@tanstack/react-router";
import { ShieldCheck } from "lucide-react";

import { useRecording } from "@/api/recordings";
import { useRunInteraction } from "@/api/voice-studio";

import { AddAsCheckButton } from "./AddAsCheckButton";

/**
 * On the engine's run page: what PayInt made of this call -- its QA score,
 * the personal data it masked, compliance violations -- and the recording as
 * PayInt plays it (redacted unless the viewer may hear the original). The
 * engine no longer signs call audio for the browser.
 */
export function RunCallIntel({ runId }: { runId: number }) {
  const intel = useRunInteraction(runId);
  const data = intel.data;
  const recording = useRecording(data?.interactionId ?? "", "auto");
  if (intel.isPending || !data) return null;
  if (!data.interactionId)
    return (
      <p className="text-sm text-muted-foreground">
        Not filed as a customer call (a test or unconnected run): no PayInt compliance record.
      </p>
    );
  const ix = data.interactionId;
  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
        <ShieldCheck className="h-4 w-4" /> Compliance &amp; QA
        {data.processing && data.processing !== "done" && (
          <span className="font-normal text-muted-foreground">· analysis {data.processing}</span>
        )}
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <Link to="/qa" className="underline">
          QA {data.qaTotal != null ? `${data.qaTotal} (${data.qaBand})` : "not scored yet"}
        </Link>
        <Link to="/redaction" className="underline">
          {data.piiMasked ?? 0} personal-data item{data.piiMasked === 1 ? "" : "s"} masked
        </Link>
        <Link to="/compliance" search={{ callId: ix }} className="underline">
          {data.violations ?? 0} violation{data.violations === 1 ? "" : "s"}
        </Link>
        <Link to="/audit" search={{ id: ix }} className="underline">
          Open in Audit
        </Link>
      </div>
      {recording.kind === "ready" ? (
        <div className="space-y-1">
          {/* The run's conversation above is the caption track. */}
          {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
          <audio src={recording.src} controls className="w-full" />
          <p className="text-xs text-muted-foreground">
            {recording.variant === "redacted"
              ? "Redacted recording: every personal-data finding is beeped."
              : "Original recording (you hold raw-PII permission)."}
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {recording.kind === "pending"
            ? "The redacted recording is still being made."
            : recording.kind === "loading"
              ? "Loading recording…"
              : recording.kind === "none"
                ? "No recording for this call."
                : "The recording could not be loaded."}
        </p>
      )}
      <AddAsCheckButton interactionId={ix} />
    </div>
  );
}
