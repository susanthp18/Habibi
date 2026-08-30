import { createLazyFileRoute } from "@tanstack/react-router";
import { PromptStudioPage } from "./prompt-studio.lazy";

export const Route = createLazyFileRoute("/agent-studio/$botId")({
  component: AgentCardEditor,
});

function AgentCardEditor() {
  const { botId } = Route.useParams();
  const { unansweredId, note } = Route.useSearch();
  // Keyed, so switching cards remounts the editor instead of re-running it with
  // the previous card's state still loaded.
  //
  // This route reuses one component instance across botIds, and the editor
  // holds a lot of state the server does not re-supply on a param change: the
  // version list, lint findings, flow issues, save status, the compile report,
  // canary settings. Resetting them by hand means a growing list that has to be
  // updated every time someone adds a field — and the failure is silent, a chip
  // from the previous card sitting in the header of this one. A key cannot rot.
  return <PromptStudioPage key={botId} botId={botId} unansweredId={unansweredId} note={note} />;
}
