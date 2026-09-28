/**
 * Host slot "@/host/PublishDialog": releasing an agent's draft to production.
 *
 * Shows the release gate (voice_studio_routing.validate_publish: approved tools,
 * credentials, channel rules for every live route of this agent), what replaces
 * what, and the agent's last Checks run, and requires a changelog note. The
 * publish itself goes through /voice-studio/agents/{id}/publish, which re-runs
 * the gate and records who released what and why.
 */
import { Link } from "@tanstack/react-router";
import { AlertTriangle, CircleCheck, CircleX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/config";
import { can, useMe } from "@/api/me";
import { usePublishAgent, useReleasePreflight, useReleaseQuality } from "@/api/voice-studio";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { SectionMessage } from "@/components/ui/section-message";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";

const CHANNEL_LABEL: Record<string, string> = {
  inbound: "inbound calls",
  outbound: "outbound calls",
  whatsapp: "WhatsApp",
};

export default function PublishDialog({
  workflowId,
  open,
  onOpenChange,
  onPublished,
  onCompare,
}: {
  workflowId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPublished: () => void;
  /** Opens the editor's diff of the draft against the live version. */
  onCompare?: () => void;
}) {
  const me = useMe();
  // Maker-checker: a Voice designer edits, a Release approver publishes.
  const mayPublish = can(me.data, "perm-agent-publish");
  const preflight = useReleasePreflight(workflowId, open);
  const publish = usePublishAgent(workflowId);
  const [note, setNote] = useState("");
  const gate = preflight.data;
  const noteOk = note.trim().length >= 3;
  // How the version being replaced did on real calls: the bar the draft must clear.
  const quality = useReleaseQuality(open ? workflowId : null);
  const live = quality.data?.find(
    (q) => gate?.liveVersion != null && q.version === gate.liveVersion,
  );

  const submit = () =>
    publish.mutate(
      { note: note.trim() },
      {
        onSuccess: (release) => {
          toast.success(`Version ${release.version ?? ""} is live`);
          setNote("");
          onOpenChange(false);
          onPublished();
        },
        onError: (e) => toast.error(`Not published: ${apiErrorMessage(e)}`),
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[36rem]">
        <DialogHeader>
          <DialogTitle>Publish to production</DialogTitle>
          <DialogDescription>
            {gate?.liveVersion
              ? `Draft v${gate.draftVersion ?? "?"} replaces live v${gate.liveVersion}.`
              : `Draft v${gate?.draftVersion ?? "?"} becomes the first live version.`}
            {gate && gate.channels.length > 0
              ? ` It answers ${gate.channels.map((c) => CHANNEL_LABEL[c] ?? c).join(", ")} as soon as it is published.`
              : " It is not routed to any channel yet."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-200 px-300">
          {!mayPublish ? (
            <SectionMessage variant="warning" icon={AlertTriangle} title="You cannot publish">
              Publishing needs a role with Publish (for example Release approver). Ask one to
              release this draft; your edits are saved.
            </SectionMessage>
          ) : null}
          {preflight.isPending ? (
            <p className="flex items-center gap-100 text-body-small text-text-subtle">
              <Spinner size="small" /> Running release checks…
            </p>
          ) : preflight.isError ? (
            <SectionMessage variant="error" icon={CircleX} title="Release checks could not run">
              {apiErrorMessage(preflight.error)}
            </SectionMessage>
          ) : gate && !gate.ok ? (
            <SectionMessage variant="error" icon={CircleX} title="Fix these before publishing">
              <ul className="list-disc space-y-050 pl-200">
                {gate.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </SectionMessage>
          ) : (
            <SectionMessage variant="success" icon={CircleCheck} title="Release checks passed" />
          )}
          {live && (
            <p className="text-body-small text-text-subtle">
              Live v{live.version} on {live.calls} real call{live.calls === 1 ? "" : "s"}: QA{" "}
              {live.qaAvg ?? "—"}, critical fails {live.criticalFailPct ?? 0}%,{" "}
              {live.violationsPer100 ?? 0} violations per 100 calls
              {live.agentPiiCalls > 0 ? `, agent spoke personal data on ${live.agentPiiCalls}` : ""}
              . <Link to="/studio/releases">Compare versions</Link>
            </p>
          )}
          {gate && gate.lastCheck === null && (
            <SectionMessage variant="warning" icon={AlertTriangle} title="No rehearsal on record">
              Run <Link to="/studio/checks">Checks</Link> to rehearse this agent against scripted
              customers before it talks to real ones.
            </SectionMessage>
          )}
          {gate?.lastCheck && gate.lastCheck.status === "done" && gate.lastCheck.failed > 0 && (
            <SectionMessage
              variant="warning"
              icon={AlertTriangle}
              title="The last rehearsal had failures"
            >
              {gate.lastCheck.passed} passed, {gate.lastCheck.failed} failed on{" "}
              {new Date(gate.lastCheck.createdAt).toLocaleString()}. Review them in{" "}
              <Link to="/studio/checks">Checks</Link>.
            </SectionMessage>
          )}
          <div className="space-y-100">
            <Label htmlFor="vs-release-note">What changed</Label>
            <Textarea
              id="vs-release-note"
              rows={3}
              value={note}
              maxLength={2000}
              placeholder="e.g. Ask for the callback time before booking it"
              onChange={(e) => setNote(e.target.value)}
            />
            <p className="text-body-small text-text-subtle">
              Saved in the release history with your name.
            </p>
          </div>
        </div>
        <DialogFooter>
          {onCompare && gate?.liveVersion && (
            <Button variant="subtle" onClick={onCompare}>
              Compare with live
            </Button>
          )}
          <Button variant="subtle" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!mayPublish || !gate?.ok || !noteOk}
            loading={publish.isPending}
            onClick={submit}
          >
            Publish
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
