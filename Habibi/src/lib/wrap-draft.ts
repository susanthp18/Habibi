// Unsaved Handoff Hub wrap-up notes, in this browser tab's session storage.
// Kept here, not beside the Hub, because signing out clears them (lib/sso).

const PREFIX = "handoff-wrap:";

/** Whose draft: the signed-in operator in their tenant. */
export type DraftOwner = { id: string; tenantId: string } | undefined;

const draftKey = (owner: NonNullable<DraftOwner>, handoffId: string) =>
  `${PREFIX}${owner.tenantId}:${owner.id}:${handoffId}`;

/** Unsaved wrap-up notes for this browser tab, kept per operator and case:
 * leaving the case (a link, the queue) must not lose what was typed, and
 * nobody else signed in to the tab ever reads them. They go when the
 * wrap-up saves, when the case stops being the operator's (taken over,
 * closed by someone else, access lost), with the tab, and at sign-out.
 * Storage can be missing or refuse (private windows); the notes then live
 * only while the case is open. */
export const wrapDraft = {
  read(owner: DraftOwner, handoffId: string): string {
    if (!owner) return "";
    try {
      return sessionStorage.getItem(draftKey(owner, handoffId)) ?? "";
    } catch {
      return "";
    }
  },
  write(owner: DraftOwner, handoffId: string, notes: string) {
    if (!owner) return;
    try {
      if (notes) sessionStorage.setItem(draftKey(owner, handoffId), notes);
      else sessionStorage.removeItem(draftKey(owner, handoffId));
    } catch {
      /* not kept: see above */
    }
  },
};

/** Every operator's drafts in this tab: signing out leaves no notes behind. */
export function clearWrapDrafts() {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith(PREFIX)) sessionStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable: nothing was kept */
  }
}
