import {
  useActiveProdDeployment,
  useDiscardPromptVersion,
  usePublishedPromptVersion,
  useEnsureStudioDraft,
  useLintPrompt,
  usePersonaPresets,
  useProdDeployments,
  usePromptVersions,
  usePublishStudioDraft,
  useRestorePromptVersionAsDraft,
  useRollbackBotDeployment,
} from "@/api/prompt-studio";
import { useAgentStudioCard, useCompileCard, useDeploymentExperiments } from "@/api/agent-studio";
import { isNotFound } from "@/api/config";

/** Every query and mutation the studio page composes, in the order it always called them. */
export function useStudioQueries(botId: string) {
  const versionsQuery = usePromptVersions(botId);
  const presetsQuery = usePersonaPresets();
  const activeDepQuery = useActiveProdDeployment(botId);
  // The live row from its own endpoint, not a scan of a 200-row page. An old
  // published row that dropped off the page flipped the header to "never
  // published" and reset the next label.
  const publishedQuery = usePublishedPromptVersion(botId);
  const prodDepsQuery = useProdDeployments(botId);
  const experimentsQuery = useDeploymentExperiments(botId);
  const cardQuery = useAgentStudioCard(botId);
  /**
   * The card cannot be edited: it is not there (404), or it was never read.
   *
   * A transient refetch failure after hydration used to be the same thing --
   * the whole editor was replaced by "Could not load" and autosave stopped,
   * for a card the page had already loaded and was holding. That is an inline
   * banner (`cardStale`) now, and autosave keeps writing against the botId it
   * already confirmed.
   */
  const cardRefused = cardQuery.isError && (isNotFound(cardQuery.error) || !cardQuery.data);
  const cardStale = cardQuery.isError && !cardRefused;
  const compileMutation = useCompileCard(botId);
  const publishMutation = usePublishStudioDraft();
  const restoreMutation = useRestorePromptVersionAsDraft();
  const ensureDraftMutation = useEnsureStudioDraft();
  const discardMutation = useDiscardPromptVersion();
  const rollbackMutation = useRollbackBotDeployment();
  const lintMutation = useLintPrompt();
  return {
    versionsQuery,
    presetsQuery,
    activeDepQuery,
    publishedQuery,
    prodDepsQuery,
    experimentsQuery,
    cardQuery,
    cardRefused,
    cardStale,
    compileMutation,
    publishMutation,
    restoreMutation,
    ensureDraftMutation,
    discardMutation,
    rollbackMutation,
    lintMutation,
  };
}
