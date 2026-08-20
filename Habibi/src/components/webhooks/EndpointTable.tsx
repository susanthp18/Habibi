import { useMemo } from "react";
import { MoreHorizontal, Zap, Pause, Play, KeyRound, Trash2, Pencil, Link2, Radio } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { Lozenge } from "@/components/ui/lozenge";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { fmtRel } from "@/data/webhooks-seed";
import { cn } from "@/lib/utils";
import {
  RecordsAvatarMark,
  RecordsTable,
  type RecordsColumn,
} from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

function StatusBadge({ status }: { status: Endpoint["status"] }) {
  const map = { active: "success", paused: "neutral", broken: "danger" } as const;
  return (
    <Lozenge tone={map[status] ?? "neutral"} className="capitalize">
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "active" && "bg-background-success-bold",
          status === "paused" && "bg-background-accent-gray-subtle",
          status === "broken" && "bg-background-danger-bold animate-pulse",
        )}
      />
      {status}
    </Lozenge>
  );
}

export function EndpointTable({
  endpoints,
  deliveries,
  selectedIds,
  activeId,
  onSelectedChange,
  onRowClick,
  onEdit,
  onTestFire,
  onTogglePause,
  onRotate,
  onDelete,
}: {
  endpoints: Endpoint[];
  deliveries: Delivery[];
  selectedIds: Set<string>;
  activeId: string | null;
  onSelectedChange: (next: Set<string>) => void;
  onRowClick: (id: string) => void;
  onEdit: (ep: Endpoint) => void;
  onTestFire: (ep: Endpoint) => void;
  onTogglePause: (ep: Endpoint) => void;
  onRotate: (ep: Endpoint) => void;
  onDelete: (ep: Endpoint) => void;
}) {
  const lastByEp = useMemo(() => {
    const map = new Map<string, Delivery>();
    for (const d of deliveries) {
      if (!map.has(d.endpointId)) map.set(d.endpointId, d);
    }
    return map;
  }, [deliveries]);

  const columns = useMemo<RecordsColumn<Endpoint>[]>(
    () => [
      {
        id: "name",
        header: "Name",
        sticky: true,
        sortable: true,
        sortValue: (ep) => ep.name,
        className: "min-w-[12rem]",
        cell: (ep) => (
          <button
            type="button"
            onClick={() => onRowClick(ep.id)}
            className={cn("flex min-w-0 items-center gap-100 text-left", activeId === ep.id && "text-text-brand")}
          >
            <RecordsAvatarMark label={ep.name || "?"} />
            <span className="min-w-0">
              <span className="block truncate font-semibold text-text hover:underline">{ep.name}</span>
              <Badge variant="outline" className="mt-025 text-body-small font-normal">
                {ep.target}
              </Badge>
            </span>
          </button>
        ),
        footer: (visible) => (
          <span>
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">endpoints</span>
          </span>
        ),
      },
      {
        id: "url",
        header: "URL",
        headerIcon: <Link2 className="h-3.5 w-3.5" />,
        sortable: true,
        sortValue: (ep) => ep.url,
        cell: (ep) => (
          <code className="block max-w-[16rem] truncate rounded bg-surface-sunken px-075 py-025 font-mono text-body-small text-text-subtle">
            {ep.url}
          </code>
        ),
      },
      {
        id: "events",
        header: "Events",
        headerIcon: <Radio className="h-3.5 w-3.5" />,
        cell: (ep) => (
          <div className="flex flex-wrap gap-050">
            {(ep.events ?? []).slice(0, 2).map((e) => (
              <RecordsTag key={e} name={e} />
            ))}
            {(ep.events?.length ?? 0) > 2 ? (
              <span className="rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
                +{ep.events.length - 2}
              </span>
            ) : null}
          </div>
        ),
      },
      {
        id: "status",
        header: "Status",
        sortable: true,
        sortValue: (ep) => (ep.status === "broken" ? 3 : ep.status === "paused" ? 2 : 1),
        cell: (ep) => <StatusBadge status={ep.status} />,
        footer: (visible) => {
          const broken = visible.filter((e) => e.status === "broken").length;
          return <span className="text-text-subtlest">{broken} broken</span>;
        },
      },
      {
        id: "last",
        header: "Last delivery",
        sortable: true,
        sortValue: (ep) => {
          const last = lastByEp.get(ep.id);
          return last?.at ? new Date(last.at).getTime() : 0;
        },
        cell: (ep) => {
          const last = lastByEp.get(ep.id);
          if (!last) return <span className="text-text-subtlest">—</span>;
          return (
            <div className="flex items-center gap-075 text-body-small text-text-subtle">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  last.status === "success" && "bg-background-success-bold",
                  last.status === "client_err" && "bg-background-warning-bold",
                  last.status === "server_err" && "bg-background-danger-bold",
                  last.status === "pending" && "bg-background-accent-gray-subtle",
                )}
              />
              {fmtRel(last.at)}
              <span className="text-text-subtlest">· {last.httpStatus}</span>
            </div>
          );
        },
      },
      {
        id: "actions",
        header: "",
        align: "right",
        cell: (ep) => {
          const isPaused = ep.status === "paused";
          return (
            <div onClick={(e) => e.stopPropagation()}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" className="h-7 w-7">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-44">
                  <DropdownMenuItem onClick={() => onEdit(ep)}>
                    <Pencil className="mr-100 h-3.5 w-3.5" /> Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onTestFire(ep)}>
                    <Zap className="mr-100 h-3.5 w-3.5" /> Test fire
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onTogglePause(ep)}>
                    {isPaused ? (
                      <>
                        <Play className="mr-100 h-3.5 w-3.5" /> Resume
                      </>
                    ) : (
                      <>
                        <Pause className="mr-100 h-3.5 w-3.5" /> Pause
                      </>
                    )}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onRotate(ep)}>
                    <KeyRound className="mr-100 h-3.5 w-3.5" /> Rotate secret
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => onDelete(ep)}
                    className="text-text-danger focus:text-text-danger-bolder"
                  >
                    <Trash2 className="mr-100 h-3.5 w-3.5" /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          );
        },
        footer: () =>
          selectedIds.size > 0 ? (
            <span className="text-text-subtlest">{selectedIds.size} selected</span>
          ) : (
            <span className="text-text-subtlest">—</span>
          ),
      },
    ],
    [
      activeId,
      lastByEp,
      onRowClick,
      onEdit,
      onTestFire,
      onTogglePause,
      onRotate,
      onDelete,
      selectedIds.size,
    ],
  );

  return (
    <RecordsTable
      rows={endpoints}
      getRowId={(ep) => ep.id}
      columns={columns}
      selectable
      selected={selectedIds}
      onSelectedChange={onSelectedChange}
      emptyMessage="No webhook endpoints yet."
      ariaLabel="Webhook endpoints table"
      defaultSort={{ id: "name", dir: 1 }}
      className="h-full min-h-0"
    />
  );
}
