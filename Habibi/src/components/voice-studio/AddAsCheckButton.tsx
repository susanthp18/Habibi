import { useNavigate } from "@tanstack/react-router";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/config";
import { scenarioFromCall } from "@/api/voice-studio";
import { Button } from "@/components/ui/button";

/**
 * Turn a real Voice Studio call into a scripted Checks scenario: its customer
 * turns replayed (masked values as test values), so a fix to the agent is
 * proven on the conversation that went wrong before it is published.
 */
export function AddAsCheckButton({ interactionId }: { interactionId: string }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const add = () => {
    setBusy(true);
    scenarioFromCall(interactionId)
      .then((s) =>
        toast.success(`Check "${s.name}" created`, {
          description: `${s.turns} customer turns. Run it against the agent in Checks.`,
          action: { label: "Open Checks", onClick: () => void navigate({ to: "/studio/checks" }) },
        }),
      )
      .catch((e: unknown) => toast.error(`Not created: ${apiErrorMessage(e)}`))
      .finally(() => setBusy(false));
  };
  return (
    <Button
      variant="outline"
      size="sm"
      className="h-400 gap-050 text-body-small"
      disabled={busy}
      onClick={add}
      title="Replay this call's customer turns against the agent in Voice Studio Checks"
    >
      <FlaskConical className="h-3.5 w-3.5" /> Add as check
    </Button>
  );
}
