import { useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/components/shell/AppShell";
import {
  importSkillZip,
  useAgentStudioSkills,
  useCloneSkill,
  useCreateSkill,
  useDeleteSkill,
} from "@/api/agent-studio";
import { USE_MOCK } from "@/api/config";
import { LoadingState } from "@/components/ui/loading-state";
import { Lozenge } from "@/components/ui/lozenge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Layers } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

/** kebab-case, matching the backend's _SLUG_RE so the 409 never surprises. */
function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export const Route = createFileRoute("/agent-studio/skills/")({
  component: SkillsIndex,
  head: () => ({
    meta: [
      { title: "Skills — Agent studio" },
      {
        name: "description",
        content: "Signed first-party skills. Unsigned drafts cannot attach to production.",
      },
    ],
  }),
});

function SkillsIndex() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isLoading, isError, error } = useAgentStudioSkills();
  const cloneSkill = useCloneSkill();
  const createSkill = useCreateSkill();
  const deleteSkill = useDeleteSkill();
  const fileRef = useRef<HTMLInputElement>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  // Shown only once a submit has been refused: naming a field wrong before the
  // reader has touched it is scolding, not validation.
  const [showErrors, setShowErrors] = useState(false);
  const newSlug = toSlug(newName);
  const slugTaken = (data ?? []).some((s) => s.slug === newSlug);
  const descriptionMissing = newDescription.trim().length === 0;

  const onCreate = async () => {
    if (!newSlug) {
      setShowErrors(true);
      toast.error("Give the skill a name");
      return;
    }
    // The backend accepts an empty description and stores it, so the only
    // symptom was a skill created with no description — while the form
    // collapsed and the typed name went with it. Refusing here keeps both.
    if (descriptionMissing) {
      setShowErrors(true);
      toast.error("A skill needs a description — it is the text the mouth always sees");
      return;
    }
    try {
      const created = await createSkill.mutateAsync({
        slug: newSlug,
        description: newDescription.trim(),
        allowedTools: [],
      });
      toast.success(`Created unsigned draft ${created.slug}`);
      setNewOpen(false);
      setNewName("");
      setNewDescription("");
      setShowErrors(false);
      void navigate({ to: "/agent-studio/skills/$skillId", params: { skillId: created.id } });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Create failed");
    }
  };

  const [clonePending, setClonePending] = useState<{ id: string; slug: string } | null>(null);
  const [cloneSlug, setCloneSlug] = useState("");

  const runClone = async (skillId: string, slug: string) => {
    if (!slug) {
      toast.error("Slug must contain a letter or digit");
      return;
    }
    try {
      await cloneSkill.mutateAsync({ skillId, slug });
      toast.success(`Cloned unsigned ${slug}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Clone failed");
    }
  };

  const onClone = (skillId: string, sourceSlug: string) => {
    setCloneSlug(toSlug(`${sourceSlug}-clone`));
    setClonePending({ id: skillId, slug: sourceSlug });
  };

  // Asked in the product's own surface rather than through `window.confirm`,
  // which paints as browser chrome titled "localhost:8080 says" and blocks the
  // renderer. The app ships the themed replacement; this was one of the last
  // Agent Studio call sites still bypassing it.
  const [deletePending, setDeletePending] = useState<{ id: string; slug: string } | null>(null);

  const runDelete = async (skillId: string, slug: string) => {
    try {
      await deleteSkill.mutateAsync(skillId);
      toast.success(`Deleted ${slug}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const onDelete = (skillId: string, slug: string) => {
    setDeletePending({ id: skillId, slug });
  };

  const onImport = async (file: File) => {
    try {
      const created = await importSkillZip(file);
      toast.success("Imported as unsigned draft");
      await qc.invalidateQueries({ queryKey: ["agent-studio", "skills"] });
      void navigate({ to: "/agent-studio/skills/$skillId", params: { skillId: created.id } });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed");
    }
  };

  return (
    <AppShell>
      <div className="flex h-full flex-col">
        <header className="flex items-center justify-between border-b border-border px-400 py-200">
          <div>
            <h1 className="heading-medium font-semibold">Skills</h1>
            <p className="text-body-small text-text-subtle">
              Descriptions are the only tokens the mouth always sees. Bodies load on activation.
              Signing is HMAC, not a badge.
            </p>
          </div>
          <div className="flex gap-100">
            <input
              ref={fileRef}
              type="file"
              accept=".zip,.md"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void onImport(file);
              }}
            />
            <Button
              type="button"
              variant="outline"
              disabled={USE_MOCK}
              title={USE_MOCK ? "Connect the API to import a pack" : "Unsigned zip becomes a draft"}
              onClick={() => fileRef.current?.click()}
            >
              Import zip
            </Button>
            <Button type="button" disabled={USE_MOCK} onClick={() => setNewOpen((v) => !v)}>
              New skill
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void navigate({ to: "/agent-studio" })}
            >
              Back to fleet
            </Button>
          </div>
        </header>
        {newOpen ? (
          <div className="border-b border-border bg-surface-sunken px-400 py-200">
            <div className="text-body font-semibold">New skill</div>
            <p className="mb-150 text-body-small text-text-subtle">
              Creates an unsigned tenant draft. Add the body and tools in the editor, then sign it —
              unsigned packs cannot attach to production (G9).
            </p>
            <div className="flex flex-wrap items-end gap-100">
              <label className="text-body-small">
                Name
                <Input
                  className="ml-075"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Premium lapse chase"
                />
              </label>
              <label className="flex-1 text-body-small">
                Description <span className="text-text-danger">*</span>
                <Input
                  className="ml-075"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  aria-invalid={showErrors && descriptionMissing}
                  placeholder="One line — this is the only text the mouth always sees."
                />
              </label>
              <Button
                type="button"
                disabled={createSkill.isPending || !newSlug || slugTaken}
                onClick={() => void onCreate()}
              >
                Create draft
              </Button>
              <Button type="button" variant="outline" onClick={() => setNewOpen(false)}>
                Cancel
              </Button>
            </div>
            <div className="mt-100 text-body-tiny text-text-subtle">
              Slug: <span className="font-mono">{newSlug || "—"}</span>
              {slugTaken ? <span className="ml-100 text-text-danger">already taken</span> : null}
            </div>
            {showErrors && descriptionMissing ? (
              <p className="mt-050 text-body-small text-text-danger">
                Description is required. It rides in every prompt this skill is attached to, so a
                blank one costs tokens and tells the model nothing.
              </p>
            ) : null}
          </div>
        ) : null}
        {isError && data ? (
          // A refetch failed but the previous response is still in cache. The
          // ternary used to swap the whole grid out for an error line, so a
          // transient blip replaced a screen full of correct data with nothing
          // — and the recovery was to reload the page that had the data.
          <div className="mx-400 mt-200 rounded-medium border border-border-warning bg-background-warning-subtler px-150 py-100 text-body-small text-text-warning-bolder">
            Could not refresh the catalog (
            {error instanceof Error ? error.message : "the API did not answer"}). The rows below are
            the last successful read.
          </div>
        ) : null}
        {isLoading && !data ? (
          <div className="grid flex-1 place-items-center">
            <LoadingState label="Loading skills" />
          </div>
        ) : isError && !data ? (
          <div className="p-400 text-text-danger">
            {error instanceof Error ? error.message : "Failed to load skills"}
          </div>
        ) : (data ?? []).length === 0 ? (
          <div className="grid flex-1 place-items-center p-400 text-center">
            <div className="max-w-md space-y-150">
              <p className="text-body font-medium">No skills in this tenant yet</p>
              <p className="text-body-small text-text-subtle">
                First-party packs sync on API boot. If this stays empty, the backend is not
                reachable or migration 0075 has not been applied. Import a zip to add a tenant draft
                — drafts stay unsigned until you sign them.
              </p>
            </div>
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 content-start gap-200 overflow-y-auto p-400 md:grid-cols-2">
            {/* Scrolls, and starts at the top.
                The grid is a flex child of `h-full flex-col` inside the
                AppShell's `overflow-hidden` main region, so with no scroll
                container of its own the list was simply cut off: seven cards
                came to 1899px inside a 574px box and the last three — the
                tenant clones — could not be reached at any window size, with
                no scrollbar to suggest they existed. `min-h-0` is what lets a
                flex child shrink below its content; `content-start` keeps the
                rows at natural height when there are only a few cards. */}

            {(data ?? []).map((skill) => {
              const deletable =
                !skill.signed &&
                !skill.hasSignedVersion &&
                (skill.origin === "tenant" || skill.origin === "gardener") &&
                (skill.attachedCards ?? []).length === 0;
              const deleteReason =
                skill.signed || skill.hasSignedVersion
                  ? "Signed packs stay — a published card may pin this slug"
                  : skill.origin === "first_party"
                    ? "First-party packs are re-seeded on API boot"
                    : (skill.attachedCards ?? []).length
                      ? `Attached to ${skill.attachedCards.join(", ")}`
                      : undefined;
              return (
                // A card, not a <button>: the Clone/Delete controls live inside
                // it, and a button inside a button is invalid DOM.
                <div
                  key={skill.id}
                  className="rounded-large border border-border bg-surface p-250 text-left focus-within:border-border-brand hover:border-border-brand"
                >
                  <div className="flex items-start justify-between gap-200">
                    <div className="flex items-center gap-150">
                      <span className="grid h-8 w-8 place-items-center rounded-full bg-background-brand-subtlest text-text-brand">
                        <Layers className="h-4 w-4" />
                      </span>
                      <div>
                        <button
                          type="button"
                          className="font-mono text-body font-semibold hover:text-text-brand"
                          onClick={() =>
                            void navigate({
                              to: "/agent-studio/skills/$skillId",
                              params: { skillId: skill.id },
                            })
                          }
                        >
                          {skill.slug}
                        </button>
                        <div className="text-body-tiny text-text-subtle">{skill.origin}</div>
                      </div>
                    </div>
                    <Lozenge tone={skill.signed ? "success" : "warning"}>
                      {skill.signatureStatus}
                    </Lozenge>
                  </div>
                  <p className="mt-150 text-body-small text-text-subtle">{skill.description}</p>
                  {skill.attachedCards?.length ? (
                    <div className="mt-100 text-body-tiny text-text-subtlest">
                      Attached: {skill.attachedCards.join(", ")}
                    </div>
                  ) : null}
                  <div className="mt-150 flex flex-wrap gap-100">
                    {(skill.allowedTools ?? []).map((t) => (
                      <Lozenge key={t} tone="neutral">
                        {t}
                      </Lozenge>
                    ))}
                  </div>
                  <div className="mt-150 flex flex-wrap gap-100">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() =>
                        void navigate({
                          to: "/agent-studio/skills/$skillId",
                          params: { skillId: skill.id },
                        })
                      }
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={cloneSkill.isPending}
                      onClick={() => void onClone(skill.id, skill.slug)}
                    >
                      Clone
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={!deletable || deleteSkill.isPending}
                      title={deleteReason}
                      onClick={() => void onDelete(skill.id, skill.slug)}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <AlertDialog
        open={clonePending !== null}
        onOpenChange={(next) => {
          if (!next) setClonePending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Clone {clonePending?.slug}?</AlertDialogTitle>
            <AlertDialogDescription>
              Creates an unsigned draft. A second clone of the same skill needs its own slug —
              reusing one overwrites the first.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <label className="text-body-small">
            Slug
            <Input
              className="mt-075"
              value={cloneSlug}
              onChange={(e) => setCloneSlug(toSlug(e.target.value))}
              placeholder="skill-clone"
            />
          </label>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!toSlug(cloneSlug) || cloneSkill.isPending}
              onClick={() => {
                const target = clonePending;
                const slug = toSlug(cloneSlug);
                setClonePending(null);
                if (target && slug) void runClone(target.id, slug);
              }}
            >
              Clone
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {/* Replaces a window.confirm — see onDelete above. */}
      <AlertDialog
        open={deletePending !== null}
        onOpenChange={(next) => {
          if (!next) setDeletePending(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {deletePending?.slug}?</AlertDialogTitle>
            <AlertDialogDescription>
              This cannot be undone. Cards that attach this skill lose it on their next publish.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep it</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const target = deletePending;
                setDeletePending(null);
                if (target) void runDelete(target.id, target.slug);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  );
}
