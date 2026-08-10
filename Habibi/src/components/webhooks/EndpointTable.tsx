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
import { Lozenge } from "@/components/ui/lozenge";
import type { Delivery, Endpoint } from "@/data/webhooks-seed";
import { fmtRel } from "@/data/webhooks-seed";
import { cn } from "@/lib/utils";

function StatusBadge({ status }: { status: Endpoint["status"] }) {
  const map = { active: "success", paused: "neutral", broken: "danger" } as const;
  return (
    <Lozenge tone={map[status]} className="capitalize">
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
      <table className="w-full text-body">
        <thead className="sticky top-0 z-10 bg-surface">
          <tr className="border-b border-border text-left text-body-small font-semibold text-text-subtlest">
            <th className="w-400 px-150 py-100">
              <Checkbox
                checked={allSelected ? true : someSelected ? "indeterminate" : false}
                onCheckedChange={(v) => onToggleAll(!!v)}
              />
            </th>
            <th className="px-150 py-100">Name</th>
            <th className="px-150 py-100">URL</th>
            <th className="px-150 py-100">Events</th>
            <th className="px-150 py-100">Status</th>
            <th className="px-150 py-100">Last delivery</th>
            <th className="w-500 px-150 py-100" />
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
                  "cursor-pointer border-b border-border transition-colors hover:bg-surface-sunken",
                  isActiveRow && "bg-background-brand-subtlest/40",
                )}
              >
                <td className="px-150 py-150" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selectedIds.has(ep.id)}
                    onCheckedChange={() => onToggleSelect(ep.id)}
                  />
                </td>
                <td className="px-150 py-150">
                  <div className="font-semibold text-text">{ep.name}</div>
                  <Badge variant="outline" className="mt-025 text-body-small font-normal">
                    {ep.target}
                  </Badge>
                </td>
                <td className="max-w-[16.25rem] px-150 py-150">
                  <code className="block truncate rounded bg-surface-sunken px-075 py-025 font-mono text-body-small text-text-subtle">
                    {ep.url}
                  </code>
                </td>
                <td className="px-150 py-150">
                  <div className="flex flex-wrap gap-050">
                    {ep.events.slice(0, 2).map((e) => (
                      <span
                        key={e}
                        className="rounded bg-background-brand-subtlest px-075 py-025 font-mono text-body-small text-text-brand"
                      >
                        {e}
                      </span>
                    ))}
                    {ep.events.length > 2 && (
                      <span className="rounded bg-surface-sunken px-075 py-025 text-body-small text-text-subtle">
                        +{ep.events.length - 2}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-150 py-150">
                  <StatusBadge status={ep.status} />
                </td>
                <td className="px-150 py-150 text-body-small text-text-subtle">
                  {last ? (
                    <div className="flex items-center gap-075">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          last.status === "success" && "bg-background-success-bold",
                          last.status === "client_err" && "bg-background-warning-bold",
                          last.status === "server_err" && "bg-background-danger-bold",
                        )}
                      />
                      {fmtRel(last.at)}
                      <span className="text-text-subtlest">· {last.httpStatus}</span>
                    </div>
                  ) : (
                    <span className="text-text-subtlest">—</span>
                  )}
                </td>
                <td className="px-150 py-150" onClick={(e) => e.stopPropagation()}>
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
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
