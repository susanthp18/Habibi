import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import { mutationErrorMessage } from "@/lib/mutation-errors";

/**
 * The record a page's drawer shows for ``id``: the loaded row when the list
 * has it, else an exact read by id -- a deep link must open its record
 * whatever page of the list it is on. Pass the page's own open-id state, not
 * the URL param: pages clear the param as soon as they read it.
 *
 * The read shares the list's key prefix, so invalidating the list refreshes
 * it. While it loads the operator sees "Opening…"; a failed read, or one that
 * finds nothing (absent and not visible to you look the same, on purpose),
 * says so and closes the drawer through ``setOpenId`` (the page's state setter).
 * A read-by-id record whose refresh fails stays open, under a standing notice
 * that it is as of its last good read, with Retry. A listed record's failed
 * refresh is the list's to show (RecordsTable says so).
 */
export function useOpenRecord<T extends { id: string }>(opts: {
  queryKey: string;
  label: string;
  id: string | null;
  list: T[] | undefined;
  fetchOne: (id: string) => Promise<T[]>;
  setOpenId: (id: null) => void;
}): T | null {
  const { queryKey, label, id, list, fetchOne, setOpenId } = opts;
  const listed = id ? list?.find((r) => r.id === id) : undefined;
  const one = useQuery({
    queryKey: [queryKey, "id", id],
    queryFn: () => fetchOne(id as string),
    enabled: Boolean(id) && !listed,
  });
  const record = listed ?? one.data?.[0] ?? null;
  const state =
    !id || record ? "open" : one.isError ? "failed" : one.isSuccess ? "missing" : "loading";
  const toastId = `open-record:${queryKey}`;
  const staleId = `open-record-stale:${queryKey}`;
  const stale = Boolean(id && !listed && one.data?.length && one.isError);
  const asOf = new Date(one.dataUpdatedAt).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
  const retry = one.refetch;

  useEffect(() => {
    if (!id) return; // closing after a failure must leave its message up
    if (state === "open") {
      toast.dismiss(toastId);
    } else if (state === "loading") {
      toast.loading(`Opening ${label} ${id}…`, { id: toastId });
    } else {
      toast.error(
        state === "failed"
          ? `Couldn't open ${label} ${id}: ${mutationErrorMessage(one.error)}`
          : `Couldn't find ${label} ${id}: it doesn't exist, or isn't visible to you`,
        { id: toastId },
      );
      setOpenId(null);
    }
  }, [state, id, label, toastId, one.error, setOpenId]);
  useEffect(() => {
    if (!stale) {
      toast.dismiss(staleId);
      return;
    }
    toast.error(`Couldn't refresh ${label} ${id}: showing it as of ${asOf}`, {
      id: staleId,
      duration: Infinity,
      action: { label: "Retry", onClick: () => void retry() },
    });
  }, [stale, staleId, label, id, asOf, retry]);
  useEffect(
    () => () => {
      toast.dismiss(toastId);
      toast.dismiss(staleId);
    },
    [toastId, staleId],
  );

  return record;
}
