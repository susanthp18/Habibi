import { useMemo } from "react";
import { Switch } from "@/components/ui/switch";
import type { FaqPair } from "@/data/kb-seed";
import { formatKbDate } from "@/lib/utils";
import { Trash2 } from "lucide-react";
import { RecordsTable, type RecordsColumn } from "@/components/records/RecordsTable";
import { RecordsTag } from "@/components/records/RecordsTag";

export function FaqTable({
  faqs,
  onSelect,
  onToggle,
  onDelete,
  selectedId,
  loading = false,
  emptyFromFilter = false,
}: {
  faqs: FaqPair[];
  onSelect: (f: FaqPair) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete?: (id: string) => void;
  selectedId?: string | null;
  loading?: boolean;
  emptyFromFilter?: boolean;
}) {
  const columns = useMemo<RecordsColumn<FaqPair>[]>(
    () => [
      {
        id: "question",
        header: "Question",
        sticky: true,
        sortable: true,
        sortValue: (f) => f.question,
        className: "min-w-[16rem]",
        cell: (f) => (
          <span className="line-clamp-2 text-body font-medium text-text" title={f.question}>
            {f.question}
          </span>
        ),
        footer: (visible) => (
          <span className="text-body-small">
            <span className="font-semibold tabular text-text">{visible.length}</span>{" "}
            <span className="text-text-subtlest">FAQs</span>
          </span>
        ),
      },
      {
        id: "answer",
        header: "Answer preview",
        className: "min-w-[18rem]",
        cell: (f) => (
          <span className="line-clamp-2 text-body-small text-text-subtle" title={f.answer}>
            {f.answer}
          </span>
        ),
      },
      {
        id: "intent",
        header: "Intent",
        sortable: true,
        sortValue: (f) => f.intent,
        className: "min-w-[8rem] whitespace-nowrap",
        cell: (f) => <RecordsTag name={f.intent} />,
      },
      {
        id: "updated",
        header: "Updated",
        sortable: true,
        sortValue: (f) => f.updatedAt,
        className: "min-w-[7rem] whitespace-nowrap",
        cell: (f) => (
          <span className="text-body-small text-text-subtle">
            {formatKbDate(f.updatedAt, { day: "2-digit", month: "short" })}
          </span>
        ),
      },
      {
        id: "enabled",
        header: "Enabled",
        align: "center",
        className: "min-w-[5.5rem]",
        cell: (f) => (
          <div onClick={(e) => e.stopPropagation()}>
            <Switch
              aria-label={`Enable FAQ: ${f.question}`}
              checked={f.enabled}
              onCheckedChange={(v) => onToggle(f.id, v)}
            />
          </div>
        ),
      },
      {
        id: "actions",
        header: "",
        align: "right",
        className: "min-w-[3.5rem]",
        cell: (f) =>
          onDelete ? (
            <div onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                onClick={() => onDelete(f.id)}
                className="rounded-medium p-075 text-text-subtlest hover:bg-background-danger-subtler hover:text-text-danger-bolder"
                aria-label="Delete FAQ"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : null,
      },
    ],
    [onDelete, onToggle],
  );

  if (!loading && faqs.length === 0) {
    return (
      <div className="flex h-full min-h-[11.25rem] flex-col items-center justify-center bg-surface px-300 py-500 text-center">
        <p className="text-body font-medium text-text">
          {emptyFromFilter ? "No matches in this view" : "No FAQ pairs"}
        </p>
        <p className="mt-050 text-body-small text-text-subtlest">
          {emptyFromFilter
            ? "Clear search to see all FAQ pairs."
            : "Add an FAQ or sync from source_db to load product Q&A."}
        </p>
      </div>
    );
  }

  return (
    <RecordsTable
      rows={faqs}
      getRowId={(f) => f.id}
      columns={columns}
      isLoading={loading}
      activeRowId={selectedId}
      onRowClick={onSelect}
      ariaLabel="FAQ pairs"
      tableClassName="min-w-[52rem]"
      className="h-full rounded-none border-0"
    />
  );
}
