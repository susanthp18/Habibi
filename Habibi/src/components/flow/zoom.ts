import { useStore } from "@xyflow/react";

/**
 * Zoom thresholds shared by the node and edge renderers.
 *
 * These live in their own module rather than alongside the node components on
 * purpose. A module that exports React components *and* something else — a
 * constant, a hook — is not eligible for React Fast Refresh, so editing it
 * invalidates the importer chain in ways that can leave two copies of a
 * component alive in one canvas: some nodes rendering from the old module, some
 * from the new, disagreeing about the very threshold they are meant to share.
 * Components-only modules on one side, plain values on the other, keeps refresh
 * predictable.
 */

/** Below this, a node card is too small to read and swaps to a key-only form. */
export const LOD_ZOOM = 0.62;

/**
 * Below this an edge label is a smudge, and the node cards paint over it anyway
 * — xyflow renders the label layer beneath `.react-flow__nodes`.
 */
export const LABEL_ZOOM = 0.8;

export function useCompact(): boolean {
  return useStore((s) => s.transform[2] < LOD_ZOOM);
}

export function useLabelsVisible(): boolean {
  return useStore((s) => s.transform[2] >= LABEL_ZOOM);
}
