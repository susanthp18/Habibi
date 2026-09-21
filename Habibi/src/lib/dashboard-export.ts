import type { DashboardData } from "@/api/dashboard";
import type { Range, Segment, TeamFilter } from "@/api/types/dashboard";

export type DashboardExportFilters = {
  range: Range;
  segment: Segment;
  team: TeamFilter;
};

function csvCell(value: unknown): string {
  if (value == null) return "";
  const text =
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
      ? String(value)
      : JSON.stringify(value);
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function row(cells: unknown[]): string {
  return cells.map(csvCell).join(",");
}

/** On-screen payload → CSV. Filename includes the filters that produced it. */
export function dashboardToCsv(data: DashboardData): string {
  const lines: string[] = [
    row(["section", "key", "label", "value", "delta"]),
    ...data.heroKpis.map((k) => row(["hero", "", k.label, k.value, k.delta])),
    ...data.kpis.map((k) => row(["kpi", k.key, k.label, k.value, k.delta])),
    "",
    row([
      "section",
      "id",
      "name",
      "account",
      "outstanding",
      "daysPastDue",
      "risk",
      "lastContact",
      "product",
    ]),
    ...data.atRiskAccounts.map((a) =>
      row([
        "at_risk",
        a.id,
        a.name,
        a.account,
        a.outstanding,
        a.daysPastDue,
        a.risk,
        a.lastContact,
        a.product,
      ]),
    ),
    "",
    row(["section", "rank", "name", "team", "calls", "aht", "upsell", "csat"]),
    ...data.leaderboard.map((r) =>
      row(["leaderboard", r.rank, r.name, r.team, r.calls, r.aht, r.upsell, r.csat]),
    ),
    "",
    row(["section", "date", "voice", "whatsapp", "chat"]),
    ...data.callVolumeStacked.map((p) => row(["volume", p.date, p.voice, p.whatsapp, p.chat])),
    "",
    row(["section", "date", "value"]),
    ...data.recoveryTrend.map((p) => row(["recovery", p.date, p.value])),
  ];
  return lines.join("\n");
}

export function dashboardFilename(filters: DashboardExportFilters): string {
  return `dashboard-${filters.range}-${filters.segment}-${filters.team}.csv`;
}

export function triggerCsvDownload(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
