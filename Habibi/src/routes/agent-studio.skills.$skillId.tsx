import { useEffect, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import {
  useAgentStudioSkill,
  usePatchSkill,
  useRevertSkill,
  useRunSkillScript,
  useSignSkill,
  useSkillScripts,
  exportSkillZip,
} from "@/api/agent-studio";
import { useFlowTools as useCatalogTools } from "@/api/flow";
import { usePromptTokenEstimate } from "@/api/prompt-studio";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { isNotFound } from "@/api/config";

export const Route = createFileRoute("/agent-studio/skills/$skillId")({
  component: SkillEditor,
  // `params.skillId` is whatever is in the URL, which is a row id as often as
  // a slug — so the browser tab read "skill-ptp-negotiate — Skill" while the
  // page header two lines below resolved and displayed "ptp-negotiate". The
  // route head cannot see the resolved row, so the component sets the title
  // once it has one; this is the pre-resolution placeholder.
  head: ({ params }) => ({
    meta: [{ title: `${params.skillId} — Skill` }],
  }),
});

function SkillEditor() {
  const { skillId } = Route.useParams();
  const navigate = useNavigate();
  const skillQuery = useAgentStudioSkill(skillId);
  const catalogQuery = useCatalogTools();
  const patch = usePatchSkill(skillId);
  const sign = useSignSkill();
  const revert = useRevertSkill();
  const runScript = useRunSkillScript();
  const scriptsQuery = useSkillScripts();
  const skill = skillQuery.data;
  const [body, setBody] = useState<string | null>(null);
  const [description, setDescription] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [scriptName, setScriptName] = useState<string | null>(null);
  const [scriptJson, setScriptJson] = useState(
    '{"outstanding": 12000, "installment_amount": 4000}',
  );

  /**
   * Drop the local edit overlay when the route points at a different skill.
   *
   * TanStack keeps this component mounted across a param change, and all four
   * pieces of local state above are "the author's unsaved edits, or null for
   * `use the server row`". None of them reset, so navigating from skill A to
   * skill B — reachable today by browser Back/Forward alone — opened B's page
   * showing A's edited description, A's body and A's tool selection, with Save
   * enabled and pointed at B. One click would have written A's text onto B.
   */
  useEffect(() => {
    setBody(null);
    setDescription(null);
    setSelected(null);
    setScriptName(null);
  }, [skillId]);

  /**
   * Name the tab after the resolved skill, not the URL.
   *
   * The route's `head` runs before the row is fetched and only has the raw
   * param, which is a row id (`skill-ptp-negotiate`) as often as a slug — so
   * the tab and the page header disagreed about the name of the thing on
   * screen.
   */
  useEffect(() => {
    if (skill?.slug) document.title = `${skill.slug} — Skill`;
  }, [skill?.slug]);

  const allowed = selected ?? skill?.allowedTools ?? [];
  const desc = description ?? skill?.description ?? "";
  const md = body ?? skill?.body ?? "";
  const catalog = catalogQuery.data ?? [];
  const scripts = scriptsQuery.data ?? [];
  // Falls back to the first catalog entry rather than a hardcoded name, so the
  // picker cannot offer a script the backend no longer allowlists.
  const activeScript = scriptName ?? scripts[0]?.name ?? "";
  const dirty =
    (description !== null && description !== (skill?.description ?? "")) ||
    (body !== null && body !== (skill?.body ?? "")) ||
    (selected !== null &&
      JSON.stringify([...selected].sort()) !==
        JSON.stringify([...(skill?.allowedTools ?? [])].sort()));

  const onSave = async () => {
    try {
      await patch.mutateAsync({ description: desc, allowedTools: allowed, body: md });
      // Drop the local overlay so the editor shows the row the server actually
      // stored — patch_skill bumps the version and may normalise the body, and
      // holding stale local state hid that.
      setDescription(null);
      setBody(null);
      setSelected(null);
      toast.success("Draft saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Save failed");
    }
  };

  // The same estimator the Prompt and Flow tabs bill against. This screen
  // counted `desc.length / 4`, so two screens disagreed about the same text —
  // and this is the one where the number is a cap the author has to author
  // under. Debounced inside the hook; the heuristic stands in until it lands so
  // the header never renders an empty figure.
  const estimateQuery = usePromptTokenEstimate({ prompt: desc });
  const tokenEstimate = estimateQuery.data?.tokens ?? Math.ceil(desc.length / 4);
  const tokensCounted = estimateQuery.data?.source === "tiktoken";

  if (skillQuery.isLoading && !skill) {
    return (
      <AppShell>
        <div className="grid h-full place-items-center">
          <LoadingState label="Loading skill" />
        </div>
      </AppShell>
    );
  }
  if (skillQuery.isError) {
    // "Skill not found." was rendered for every failure mode this query has —
    // a 500, a timeout, the API being unreachable — so the one screen that
    // could tell you the skill still exists confidently told you it does not.
    const notFound = isNotFound(skillQuery.error);
    return (
      <AppShell>
        <div className="grid h-full place-items-center p-400">
          <div className="max-w-md space-y-100 text-center">
            <p className="text-body font-semibold text-text">
              {notFound ? "Skill not found" : "Could not load this skill"}
            </p>
            <p className="text-body-small text-text-subtle">
              {notFound
                ? `Nothing in the catalog is registered as “${skillId}”.`
                : skillQuery.error instanceof Error
                  ? skillQuery.error.message
                  : "The API did not answer. This is a failed read, not a missing skill."}
            </p>
            <Button
              type="button"
              variant="outline"
              className="mt-100"
              onClick={() => void navigate({ to: "/agent-studio/skills" })}
            >
              Back to the library
            </Button>
          </div>
        </div>
      </AppShell>
    );
  }
  if (!skill) {
    return (
      <AppShell>
        <div className="p-400 text-text-danger">Skill not found.</div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="flex h-full min-h-0 flex-col">
        <header className="flex items-center justify-between border-b border-border px-400 py-200">
          <div>
            <div className="font-mono heading-medium font-semibold">{skill.slug}</div>
            <div className="text-body-small text-text-subtle">
              Tools are a catalog multi-select — never free text. Prefix tokens{" "}
              {tokensCounted ? "" : "≈ "}
              {tokenEstimate} (cap 120).
            </div>
          </div>
          <div className="flex gap-100">
            <Button
              type="button"
              variant="outline"
              onClick={() => void navigate({ to: "/agent-studio/skills" })}
            >
              Library
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                void navigate({
                  to: "/sandbox",
                  search: {
                    skillSlug: skill.slug,
                    // The card this skill is actually attached to. It was
                    // hardcoded to kaia-v2-4, so opening the sandbox from an
                    // insurance-only skill loaded the collections bot and
                    // sandboxed a skill that card does not carry — a green run
                    // that proves nothing about the skill you were editing.
                    botId: skill.attachedCards?.[0] ?? "kaia-v2-4",
                  },
                })
              }
            >
              Load in sandbox
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                void exportSkillZip(skill.id).catch((err: unknown) =>
                  toast.error(err instanceof Error ? err.message : "Export failed"),
                )
              }
            >
              Export zip
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={patch.isPending || !dirty}
              onClick={() => void onSave()}
            >
              {patch.isPending ? "Saving…" : dirty ? "Save draft" : "Saved"}
            </Button>
            <Button
              type="button"
              disabled={sign.isPending || skill.signed}
              onClick={() =>
                void sign
                  .mutateAsync(skill.id)
                  .then(() => toast.success("Signed"))
                  // Revert and Run both catch; this one did not, so a failed
                  // sign produced no toast, no state change and an unhandled
                  // rejection in the console — indistinguishable from a click
                  // that did not register.
                  .catch((err: unknown) =>
                    toast.error(err instanceof Error ? err.message : "Sign failed"),
                  )
              }
            >
              Sign
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={revert.isPending || skill.signed || !skill.hasSignedVersion}
              title={
                skill.signed
                  ? "Latest is already the signed version"
                  : "Restore the last signed version as latest"
              }
              onClick={() =>
                void revert
                  .mutateAsync({ skillId: skill.id })
                  .then(() => toast.success("Reverted to last signed version"))
                  .catch((err: Error) => toast.error(err.message))
              }
            >
              Revert to signed
            </Button>
          </div>
        </header>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-250 overflow-y-auto p-250 xl:grid-cols-[1fr_320px]">
          <div className="space-y-200">
            <label className="block space-y-050">
              <span className="text-body-small font-medium">
                Description (always in the prefix)
              </span>
              <textarea
                className="min-h-24 w-full rounded-medium border border-border bg-surface p-150 text-body"
                value={desc}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <div>
              <div className="mb-050 text-body-small font-medium">Allowed tools</div>
              <div className="flex flex-wrap gap-100 rounded-medium border border-border p-150">
                {catalog.map((t) => {
                  const on = allowed.includes(t.key);
                  return (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() =>
                        setSelected(on ? allowed.filter((n) => n !== t.key) : [...allowed, t.key])
                      }
                      className={
                        on
                          ? "rounded-medium border border-border-brand bg-background-brand-subtlest px-100 py-050 font-mono text-body-tiny"
                          : "rounded-medium border border-border px-100 py-050 font-mono text-body-tiny text-text-subtle"
                      }
                    >
                      {t.key}
                    </button>
                  );
                })}
              </div>
            </div>
            <label className="block space-y-050">
              <span className="text-body-small font-medium">Body (loaded on activation)</span>
              <textarea
                className="min-h-64 w-full rounded-medium border border-border bg-surface p-150 font-mono text-body-small"
                value={md}
                onChange={(e) => setBody(e.target.value)}
              />
            </label>
            <div className="rounded-medium border border-border p-150">
              <div className="text-body-small font-medium">Preview</div>
              <pre className="mt-100 max-h-48 overflow-auto whitespace-pre-wrap font-sans text-body-small text-text-subtle">
                {md || "Empty body"}
              </pre>
            </div>
            <div className="rounded-medium border border-border p-150">
              <div className="text-body-small font-medium">
                references/ (lazy, never grants tools)
              </div>
              <ul className="mt-100 space-y-050 font-mono text-body-tiny text-text-subtle">
                {Object.keys(skill.pack?.references ?? {}).length === 0 &&
                (skill.referenceFiles ?? []).length === 0 ? (
                  <li>No reference files in this pack.</li>
                ) : (
                  Object.keys(skill.pack?.references ?? {})
                    .concat(skill.referenceFiles ?? [])
                    .filter((n, i, a) => a.indexOf(n) === i)
                    .map((name) => <li key={name}>{name}</li>)
                )}
              </ul>
            </div>
          </div>
          <aside className="space-y-200">
            <div className="rounded-medium border border-border p-150">
              <div className="text-body font-medium">Signature</div>
              <Lozenge tone={skill.signed ? "success" : "warning"}>{skill.signatureStatus}</Lozenge>
              <p className="mt-100 text-body-tiny text-text-subtle">
                Gardener drafts stay unsigned until a human signs. G9 fails closed otherwise. Save
                on a signed pack creates a new draft — it does not overwrite production.
              </p>
            </div>
            {(skill.versions ?? []).length > 0 ? (
              <div className="rounded-medium border border-border p-150">
                <div className="text-body font-medium">Versions</div>
                <ul className="mt-100 space-y-050">
                  {(skill.versions ?? []).map((v) => (
                    <li
                      key={v.id}
                      className="flex items-center justify-between gap-100 text-body-tiny"
                    >
                      <span className="font-mono">
                        v{v.version} · {v.status}
                        {v.id === skill.latestVersionId ? " · latest" : ""}
                      </span>
                      {v.status === "signed" && v.id !== skill.latestVersionId ? (
                        <button
                          type="button"
                          className="text-text-brand"
                          onClick={() =>
                            void revert
                              .mutateAsync({ skillId: skill.id, versionId: v.id })
                              .then(() => toast.success(`Reverted to v${v.version}`))
                              .catch((err: Error) => toast.error(err.message))
                          }
                        >
                          Restore
                        </button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <div className="rounded-medium border border-border p-150">
              <div className="text-body font-medium">Code-mode</div>
              <p className="text-body-tiny text-text-subtle">JSON in, JSON out. No terminal.</p>
              <select
                className="mt-100 w-full rounded-medium border border-border bg-surface px-100 py-050 text-body-small"
                value={activeScript}
                disabled={scripts.length === 0}
                onChange={(e) => setScriptName(e.target.value)}
              >
                {scripts.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
              <textarea
                className="mt-100 min-h-24 w-full rounded-medium border border-border bg-surface p-100 font-mono text-body-tiny"
                value={scriptJson}
                onChange={(e) => setScriptJson(e.target.value)}
              />
              <Button
                type="button"
                variant="outline"
                className="mt-100"
                disabled={runScript.isPending || !activeScript}
                onClick={() => {
                  let payload: Record<string, unknown>;
                  try {
                    // `JSON.parse` succeeds on `[1,2]`, `"x"` and `7` too, and
                    // the unchecked cast let all of them through. The backend
                    // then substituted `{}` and ran the script against no
                    // arguments, returning `numeric_required` — which reads
                    // exactly like a verdict on the input, computed from input
                    // that was never looked at.
                    const parsed: unknown = JSON.parse(scriptJson);
                    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
                      toast.error("Payload must be a JSON object — not an array or a bare value.");
                      return;
                    }
                    payload = parsed as Record<string, unknown>;
                  } catch {
                    toast.error("Payload is not valid JSON");
                    return;
                  }
                  // Was an un-awaited mutateAsync with no catch: a transport
                  // failure surfaced as an unhandled rejection and the panel
                  // just sat there.
                  void runScript
                    .mutateAsync({ name: activeScript, payload })
                    .catch((err: unknown) =>
                      toast.error(err instanceof Error ? err.message : "Script failed"),
                    );
                }}
              >
                Run
              </Button>
              {runScript.data ? (
                <pre className="mt-100 overflow-auto rounded-medium bg-surface-sunken p-100 text-body-tiny">
                  {JSON.stringify(runScript.data, null, 2)}
                </pre>
              ) : null}
            </div>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
