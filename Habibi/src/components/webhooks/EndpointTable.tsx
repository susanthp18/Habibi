import { MoreHorizontal, Zap, Pause, Play, KeyRound, Trash2, Pencil } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { fmtRel } from "@/data/webhooks-seed";
import { cn } from "@/lib/utils";

function StatusBadge({ status }: { status: Endpoint["status"] }) {
  const map = {
    active: "bg-emerald-100 text-emerald-700 border-emerald-200",
    paused: "bg-slate-100 text-slate-700 border-slate-200",
    broken: "bg-rose-100 text-rose-700 border-rose-200",
  } as const;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize",
        map[status],
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "active" && "bg-emerald-500",
          status === "paused" && "bg-slate-400",
          status === "broken" && "bg-rose-500 animate-pulse",
        )}
      />
      {status}
    </span>
  );
}

export function EndpointTable({
  endpoints,
  deliveries,
  selectedIds,
  activeId,
  onToggleSelect,
  onToggleAll,
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
  onToggleSelect: (id: string) => void;
  onToggleAll: (v: boolean) => void;
  onRowClick: (id: string) => void;
  onEdit: (ep: Endpoint) => void;
  onTestFire: (ep: Endpoint) => void;
  onTogglePause: (ep: Endpoint) => void;
  onRotate: (ep: Endpoint) => void;
  onDelete: (ep: Endpoint) => void;
}) {
  const lastByEp = new Map<string, Delivery>();
  for (const d of deliveries) {
    if (!lastByEp.has(d.endpointId)) lastByEp.set(d.endpointId, d);
  }

  const allSelected = endpoints.length > 0 && endpoints.every((e) => selectedIds.has(e.id));
  const someSelected = endpoints.some((e) => selectedIds.has(e.id));

  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full text-[13px]">
        <thead className="sticky top-0 z-10 bg-surface-card">
          <tr className="border-b border-[var(--border-token)] text-left text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            <th className="w-8 px-3 py-2">
              <Checkbox
                checked={allSelected ? true : someSelected ? "indeterminate" : false}
                onCheckedChange={(v) => onToggleAll(!!v)}
              />
            </th>
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">URL</th>
            <th className="px-3 py-2">Events</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Last delivery</th>
            <th className="w-10 px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep) => {
            const last = lastByEp.get(ep.id);
            const isActiveRow = activeId === ep.id;
            const isPaused = ep.status === "paused";
            return (
              <tr
                key={ep.id}
                onClick={() => onRowClick(ep.id)}
                className={cn(
                  "cursor-pointer border-b border-[var(--border-token)] transition-colors hover:bg-surface-sunken",
                  isActiveRow && "bg-brand-tint/40",
                )}
              >
                <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selectedIds.has(ep.id)}
                    onCheckedChange={() => onToggleSelect(ep.id)}
                  />
                </td>
                <td className="px-3 py-3">
                  <div className="font-semibold text-brand-navy">{ep.name}</div>
                  <Badge variant="outline" className="mt-0.5 text-[10px] font-normal">
                    {ep.target}
                  </Badge>
                </td>
                <td className="max-w-[260px] px-3 py-3">
                  <code className="block truncate rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
                    {ep.url}
                  </code>
                </td>
                <td className="px-3 py-3">
                  <div className="flex flex-wrap gap-1">
                    {ep.events.slice(0, 2).map((e) => (
                      <span
                        key={e}
                        className="rounded bg-brand-tint px-1.5 py-0.5 font-mono text-[10px] text-brand-primary-dark"
                      >
                        {e}
                      </span>
                    ))}
                    {ep.events.length > 2 && (
                      <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] text-text-secondary">
                        +{ep.events.length - 2}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-3">
                  <StatusBadge status={ep.status} />
                </td>
                <td className="px-3 py-3 text-[12px] text-text-secondary">
                  {last ? (
                    <div className="flex items-center gap-1.5">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          last.status === "success" && "bg-emerald-500",
                          last.status === "client_err" && "bg-amber-500",
                          last.status === "server_err" && "bg-rose-500",
                        )}
                      />
                      {fmtRel(last.at)}
                      <span className="text-text-muted">· {last.httpStatus}</span>
                    </div>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
                <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="icon" variant="ghost" className="h-7 w-7">
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-44">
                      <DropdownMenuItem onClick={() => onEdit(ep)}>
                        <Pencil className="mr-2 h-3.5 w-3.5" /> Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onTestFire(ep)}>
                        <Zap className="mr-2 h-3.5 w-3.5" /> Test fire
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onTogglePause(ep)}>
                        {isPaused ? (
                          <>
                            <Play className="mr-2 h-3.5 w-3.5" /> Resume
                          </>
                        ) : (
                          <>
                            <Pause className="mr-2 h-3.5 w-3.5" /> Pause
                          </>
                        )}
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => onRotate(ep)}>
                        <KeyRound className="mr-2 h-3.5 w-3.5" /> Rotate secret
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onClick={() => onDelete(ep)}
                        className="text-rose-600 focus:text-rose-700"
                      >
                        <Trash2 className="mr-2 h-3.5 w-3.5" /> Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
