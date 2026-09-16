/**
 * The knowledge-base screen's UI state, in one place.
 *
 * Twenty-three `useState`s -- selection, four dialogs, the FAQ editor, the
 * upload wizard, the filters and six busy flags -- became one reducer so a
 * confirm cannot be left open while the thing it confirms is gone, and a
 * dialog's "which id" travels with its "open".
 */
import type { FaqPair, KbChunk, KbPurgeScope } from "@/api/kb";
import type { KbDocType } from "@/api/types/kb";

export type KbConfirm =
  | { kind: "sync" }
  | { kind: "purge"; scope: KbPurgeScope }
  | { kind: "deleteDoc"; id: string }
  | { kind: "deleteFaq"; id: string };

export interface KbFilters {
  search: string;
  type: "all" | KbDocType;
  enabled: "all" | "enabled" | "disabled";
  showResolved: boolean;
}

export interface KbState {
  selectedDocId: string | null;
  openChunk: KbChunk | null;
  /** The wizard, and the gap the upload should be linked to when it came from one. */
  upload: { open: boolean; gapId: string | null };
  /** The editor sheet; `editing` null is a new FAQ; `gapId` links the FAQ on create. */
  faq: { open: boolean; editing: FaqPair | null; gapId: string | null };
  filters: KbFilters;
  confirm: KbConfirm | null;
  busy: {
    reindexing: ReadonlySet<string>;
    savingMeta: boolean;
    reindexAll: boolean;
    sync: boolean;
    purge: boolean;
    deletingId: string | null;
  };
}

export const INITIAL_KB_STATE: KbState = {
  selectedDocId: null,
  openChunk: null,
  upload: { open: false, gapId: null },
  faq: { open: false, editing: null, gapId: null },
  filters: { search: "", type: "all", enabled: "all", showResolved: false },
  confirm: null,
  busy: {
    reindexing: new Set(),
    savingMeta: false,
    reindexAll: false,
    sync: false,
    purge: false,
    deletingId: null,
  },
};

export type KbAction =
  | { type: "select"; id: string | null }
  | { type: "openChunk"; chunk: KbChunk | null }
  | { type: "upload"; open: boolean; gapId?: string | null }
  | { type: "faq"; open: boolean; editing?: FaqPair | null; gapId?: string | null }
  | { type: "filters"; patch: Partial<KbFilters> }
  | { type: "confirm"; confirm: KbConfirm | null }
  | { type: "purgeScope"; scope: KbPurgeScope }
  | { type: "reindexing"; id: string; on: boolean }
  | { type: "reindexingAll"; ids: Iterable<string> }
  | { type: "busy"; patch: Partial<Omit<KbState["busy"], "reindexing">> };

export function kbReducer(state: KbState, action: KbAction): KbState {
  switch (action.type) {
    case "select":
      return { ...state, selectedDocId: action.id };
    case "openChunk":
      return { ...state, openChunk: action.chunk };
    case "upload":
      return {
        ...state,
        upload: { open: action.open, gapId: action.open ? (action.gapId ?? null) : null },
      };
    case "faq":
      return {
        ...state,
        faq: action.open
          ? { open: true, editing: action.editing ?? null, gapId: action.gapId ?? null }
          : { open: false, editing: null, gapId: null },
      };
    case "filters":
      return { ...state, filters: { ...state.filters, ...action.patch } };
    case "confirm":
      return { ...state, confirm: action.confirm };
    case "purgeScope":
      return state.confirm?.kind === "purge"
        ? { ...state, confirm: { ...state.confirm, scope: action.scope } }
        : state;
    case "reindexing": {
      const next = new Set(state.busy.reindexing);
      if (action.on) next.add(action.id);
      else next.delete(action.id);
      return { ...state, busy: { ...state.busy, reindexing: next } };
    }
    case "reindexingAll":
      return { ...state, busy: { ...state.busy, reindexing: new Set(action.ids) } };
    case "busy":
      return { ...state, busy: { ...state.busy, ...action.patch } };
  }
}
