import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { useAgentStudioCards } from "@/api/agent-studio";
import { useKbSnapshots } from "@/api/kb";
import { usePromptVersions } from "@/api/prompt-studio";
import { useSandboxScenarios } from "@/api/sandbox";
import { useAgentStudioSkills } from "@/api/skills";

export type SandboxSearch = { promptVersionId?: string; skillSlug?: string; botId?: string };

/**
 * What the sandbox rehearses: which card, which version, which skill,
 * scenario and KB snapshot. Seeded from the URL, then owned here.
 */
export function useSandboxSelection(search: SandboxSearch) {
  const {
    promptVersionId: searchPromptId,
    skillSlug: searchSkillSlug,
    botId: searchBotId,
  } = search;
  const cardsQuery = useAgentStudioCards();
  const skillsQuery = useAgentStudioSkills();
  const [botId, setBotId] = useState(searchBotId || "");
  // useState seeds once. Navigating to /sandbox?botId=X from an already-mounted
  // sandbox — which is what the fleet index's Sandbox button does when the tab
  // is open — left the previous card selected and silently rehearsed the wrong
  // agent. Only follows the URL when it names a card, so clearing the param
  // does not yank a selection made here.
  useEffect(() => {
    if (searchBotId) setBotId(searchBotId);
  }, [searchBotId]);
  // Without a card in the URL, rehearse the fleet's door -- the card inbound
  // traffic resolves to -- once the roster is in.
  const entryBotId = cardsQuery.data?.[0]?.entryBotId;
  useEffect(() => {
    if (!botId && entryBotId) setBotId(entryBotId);
  }, [botId, entryBotId]);
  const [skillSlug, setSkillSlug] = useState(searchSkillSlug || "");
  const versionsQuery = usePromptVersions(botId);
  const scenariosQuery = useSandboxScenarios();
  const snapshotsQuery = useKbSnapshots();

  const versions = versionsQuery.data ?? [];
  const scenarios = scenariosQuery.data ?? [];
  const kbOptions = useMemo(() => {
    const rows = snapshotsQuery.data ?? [];
    return [
      { id: "current", label: "Current (live index)" },
      ...rows.map((s) => ({ id: s.id, label: s.label || s.id })),
    ];
  }, [snapshotsQuery.data]);

  const publishedPrompt = versions.find((v) => v.status === "published") ?? versions[0] ?? null;

  const [promptVersionId, setPromptVersionId] = useState<string>("");
  const [kbSnapshotId, setKbSnapshotId] = useState("current");
  const [scenarioId, setScenarioId] = useState<string>("");

  // A requested version that belongs to a different card used to fall through
  // to this bot's published one without a word, so "Try in sandbox" on any
  // non-default card rehearsed the wrong agent and looked fine doing it.
  const warnedMissingVersion = useRef(false);
  useEffect(() => {
    if (!versions.length) return;
    if (searchPromptId) {
      if (versions.some((v) => v.id === searchPromptId)) {
        setPromptVersionId(searchPromptId);
        return;
      }
      if (!warnedMissingVersion.current) {
        warnedMissingVersion.current = true;
        toast.error(`Version ${searchPromptId} is not on ${botId}`, {
          description: "Pick the right agent above — this run would test a different card.",
        });
      }
    }
    if (!promptVersionId) {
      setPromptVersionId(publishedPrompt?.id ?? versions[0]!.id);
    }
  }, [versions, searchPromptId, publishedPrompt, promptVersionId, botId]);

  useEffect(() => {
    if (!scenarios.length) return;
    if (!scenarioId) setScenarioId(scenarios[0]!.id);
  }, [scenarios, scenarioId]);

  const scenario = scenarios.find((s) => s.id === scenarioId) ?? scenarios[0];
  const activePrompt =
    versions.find((v) => v.id === promptVersionId) ?? publishedPrompt ?? versions[0];
  const attachedSkills = useMemo(() => {
    const card = activePrompt?.agentCard as { skills?: { skill_id?: string }[] } | undefined;
    const attached = new Set(
      (card?.skills ?? []).map((s) => String(s.skill_id ?? "")).filter(Boolean),
    );
    return (skillsQuery.data ?? [])
      .filter((s) => attached.has(s.slug))
      .map((s) => ({ slug: s.slug, label: s.slug }));
  }, [activePrompt, skillsQuery.data]);
  const activeKb = kbOptions.find((k) => k.id === kbSnapshotId) ?? kbOptions[0]!;

  return {
    cards: (cardsQuery.data ?? []).map((c) => ({ id: c.botId, label: c.name })),
    botId,
    setBotId,
    skillSlug,
    setSkillSlug,
    versions,
    scenarios,
    kbOptions,
    promptVersionId,
    setPromptVersionId,
    kbSnapshotId,
    setKbSnapshotId,
    scenarioId,
    setScenarioId,
    scenario,
    activePrompt,
    attachedSkills,
    activeKb,
    loading: scenariosQuery.isLoading || versionsQuery.isLoading,
  };
}
