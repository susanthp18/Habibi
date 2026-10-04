import { useEffect, useState } from "react";
import { createLazyFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { HandoffCase, StaleBanner } from "@/components/handoff/HandoffCase";
import { HandoffCaseload, HandoffQueueList } from "@/components/handoff/HandoffQueue";
import { handoffErrorWords, isAccessLoss, wrapDraft } from "@/components/handoff/handoff-words";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryErrorBanner } from "@/components/ui/query-state";
import { can, useMe } from "@/api/me";
import { useDebounced } from "@/lib/use-debounced";
import { useClaimHandoff, useHandoffQueue, useHandoffSession } from "@/api/handoff";

export const Route = createLazyFileRoute("/_app/handoff")({
  component: HandoffPage,
});

type ClaimError = { interactionId: string; message: string };

/** The queue shows this many more each time, up to what the server serves. */
const PAGE = 50;
const MAX_ROWS = 500;

function HandoffPage() {
  const { interactionId, customerId, mode } = Route.useSearch();
  const navigate = useNavigate({ from: "/handoff" });
  const claimMut = useClaimHandoff();
  const [claimError, setClaimError] = useState<ClaimError | null>(null);

  const claim = (id: string) => {
    setClaimError(null);
    claimMut.mutate(
      { interactionId: id },
      {
        onSuccess: (session) => {
          void navigate({ search: { interactionId: session.interactionId, customerId } });
        },
        onError: (e) => setClaimError({ interactionId: id, message: handoffErrorWords(e) }),
      },
    );
  };

  if (interactionId) {
    return (
      <CasePage
        // A new case starts clean: nothing typed or ticked for one leaks into the next.
        key={interactionId}
        interactionId={interactionId}
        monitor={mode === "monitor"}
        onClaim={claim}
        claiming={claimMut.isPending}
        claimError={claimError?.interactionId === interactionId ? claimError.message : null}
      />
    );
  }
  return (
    <QueuePage
      customerId={customerId}
      onClaim={claim}
      claimingId={claimMut.isPending ? claimMut.variables?.interactionId : null}
      claimError={claimError}
    />
  );
}

function QueuePage({
  customerId,
  onClaim,
  claimingId,
  claimError,
}: {
  customerId?: string;
  onClaim: (id: string) => void;
  claimingId: string | null | undefined;
  claimError: ClaimError | null;
}) {
  const { data: me } = useMe();
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(PAGE);
  // The server is asked when typing pauses; until its answer the list says
  // it is the previous one.
  const query = useDebounced(search);
  const queue = useHandoffQueue({ customerId, search: query, limit });
  const searching = search.trim() !== query.trim() || queue.isPlaceholderData;
  if (queue.isError && !queue.data) {
    return (
      <div className="grid h-full place-items-center p-400">
        <QueryErrorBanner label="the handoff queue" error={queue.error} />
      </div>
    );
  }
  if (!queue.data) return <HandoffSkeleton />;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      {queue.isRefetchError ? <StaleBanner at={queue.dataUpdatedAt} what="the queue" /> : null}
      <div className="mx-auto w-full max-w-2xl space-y-300 p-200">
        <HandoffCaseload items={queue.data.mine} customerId={customerId} />
        <HandoffQueueList
          items={queue.data.items}
          total={queue.data.total}
          search={search}
          searching={searching}
          onSearch={(value) => {
            setSearch(value);
            setLimit(PAGE);
          }}
          onShowMore={
            limit < MAX_ROWS ? () => setLimit((n) => Math.min(n + PAGE, MAX_ROWS)) : undefined
          }
          canClaim={can(me, "perm-interactions-write")}
          claimingId={claimingId}
          claimError={claimError}
          onClaim={onClaim}
        />
      </div>
    </div>
  );
}

function CasePage({
  interactionId,
  monitor,
  onClaim,
  claiming,
  claimError,
}: {
  interactionId: string;
  monitor: boolean;
  onClaim: (id: string) => void;
  claiming: boolean;
  claimError: string | null;
}) {
  const q = useHandoffSession(interactionId);
  const { data: me } = useMe();
  // Taken over, reassigned or gone is not a blip: the last snapshot would
  // still say the case is the reader's -- and its unsaved notes go too.
  const lost = q.isError && isAccessLoss(q.error);
  const handoffId = q.data?.handoffId;
  useEffect(() => {
    if (lost && handoffId && me)
      wrapDraft.write({ id: me.id, tenantId: me.tenantId }, handoffId, "");
  }, [lost, handoffId, me]);
  if (!q.data || lost) {
    if (q.isError) {
      return (
        <div className="flex h-full w-full flex-col items-center justify-center gap-150 bg-surface p-300">
          {lost ? (
            <p role="alert" className="max-w-md text-center text-body text-text">
              You no longer have access to this case. It may have been taken over, reassigned or
              closed.
            </p>
          ) : (
            <QueryErrorBanner label="the case" error={q.error} />
          )}
          <Link to="/handoff" search={{}} className="text-body-small font-semibold text-text-brand">
            Back to queue
          </Link>
        </div>
      );
    }
    return <HandoffSkeleton />;
  }
  return (
    <HandoffCase
      session={q.data}
      monitor={monitor || q.data.monitor}
      stale={q.isRefetchError ? q.dataUpdatedAt : null}
      onClaim={() => onClaim(interactionId)}
      claiming={claiming}
      claimError={claimError}
    />
  );
}

function HandoffSkeleton() {
  return (
    <div
      className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-surface"
      aria-busy="true"
    >
      <Skeleton className="h-800 w-full rounded-none" />
      <div className="flex min-h-0 flex-1 gap-150 p-150">
        <div className="flex min-w-0 flex-1 flex-col gap-150">
          <Skeleton className="h-24 w-full rounded-large" />
          <Skeleton className="min-h-0 flex-1 rounded-large" />
        </div>
        <div className="hidden w-[22.5rem] shrink-0 flex-col gap-150 lg:flex xl:w-[25rem]">
          <Skeleton className="h-48 rounded-large" />
          <Skeleton className="h-40 rounded-large" />
          <Skeleton className="h-40 rounded-large" />
        </div>
      </div>
    </div>
  );
}
