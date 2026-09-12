/** The four confirmations the knowledge base asks: sync, purge, delete a document, delete a FAQ. */
import type { Dispatch } from "react";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SelectField } from "@/components/ui/select";
import type { FaqPair, KbDocument, KbPurgeScope } from "@/api/kb";
import type { KbAction, KbState } from "./kbState";

export function KbConfirmDialogs({
  state,
  dispatch,
  docs,
  faqs,
  onSync,
  onPurge,
  onDeleteDoc,
  onDeleteFaq,
}: {
  state: KbState;
  dispatch: Dispatch<KbAction>;
  docs: KbDocument[];
  faqs: FaqPair[];
  onSync: () => void;
  onPurge: () => void;
  onDeleteDoc: (id: string) => void;
  onDeleteFaq: (id: string) => void;
}) {
  const { confirm, busy } = state;
  const close = () => dispatch({ type: "confirm", confirm: null });
  const pendingDeleteDoc =
    confirm?.kind === "deleteDoc" ? docs.find((d) => d.id === confirm.id) : null;
  const pendingDeleteFaq =
    confirm?.kind === "deleteFaq" ? faqs.find((f) => f.id === confirm.id) : null;
  const purge = confirm?.kind === "purge" ? confirm : null;

  return (
    <>
      <AlertDialog open={confirm?.kind === "sync"} onOpenChange={(open) => !open && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Sync from source_db?</AlertDialogTitle>
            <AlertDialogDescription>
              Re-reads policy, benefits and FAQ files from disk, re-embeds changed content, and
              replaces product FAQ pairs. Uploaded-only documents are left untouched. Azure
              embedding calls may take several minutes.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={onSync}>Sync corpus</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={purge !== null} onOpenChange={(open) => !open && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete documents</AlertDialogTitle>
            <AlertDialogDescription>
              Hard-deletes matching documents and related chunks. Type DELETE to confirm.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-150">
            <div>
              <Label className="text-body-small text-text-subtlest">Scope</Label>
              <SelectField
                aria-label="Scope"
                className="mt-050"
                value={purge?.scope ?? "uploads"}
                onChange={(v) => dispatch({ type: "purgeScope", scope: v as KbPurgeScope })}
                options={[
                  { value: "uploads", label: "Uploaded docs only (safe default)" },
                  { value: "corpus", label: "Corpus docs from source_db" },
                  { value: "all", label: "Entire knowledge base" },
                ]}
              />
            </div>
            <div>
              <Label className="text-body-small text-text-subtlest">Type DELETE</Label>
              <Input
                className="mt-050"
                value={purge?.typed ?? ""}
                onChange={(e) => dispatch({ type: "purgeTyped", typed: e.target.value })}
                placeholder="DELETE"
                autoComplete="off"
              />
            </div>
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-background-danger-bold hover:bg-background-danger-bold-pressed"
              disabled={(purge?.typed ?? "").trim().toUpperCase() !== "DELETE" || busy.purge}
              onClick={(e) => {
                e.preventDefault();
                onPurge();
              }}
            >
              {busy.purge ? "Deleting…" : "Delete permanently"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirm?.kind === "deleteDoc"} onOpenChange={(open) => !open && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{pendingDeleteDoc?.title ?? "document"}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Permanently removes this document and its chunks. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-background-danger-bold hover:bg-background-danger-bold-pressed"
              disabled={confirm?.kind !== "deleteDoc" || busy.deletingId === confirm.id}
              onClick={(e) => {
                e.preventDefault();
                if (confirm?.kind === "deleteDoc") onDeleteDoc(confirm.id);
              }}
            >
              Delete permanently
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={confirm?.kind === "deleteFaq"} onOpenChange={(open) => !open && close()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete “{pendingDeleteFaq?.question ?? "FAQ"}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Permanently removes this FAQ pair. Linked analytics gaps keep their question but lose
              the FAQ link.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-background-danger-bold hover:bg-background-danger-bold-pressed"
              disabled={confirm?.kind !== "deleteFaq"}
              onClick={(e) => {
                e.preventDefault();
                if (confirm?.kind === "deleteFaq") onDeleteFaq(confirm.id);
              }}
            >
              Delete permanently
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
