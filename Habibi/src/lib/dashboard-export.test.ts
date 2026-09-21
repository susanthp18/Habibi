import { describe, expect, it } from "vitest";

import type { DashboardData } from "@/api/dashboard";
import { dashboardFilename, dashboardToCsv } from "./dashboard-export";

const sample: DashboardData = {
  heroKpis: [
    {
      label: "Avg Handle Time (AHT)",
      value: "2m 10s",
      raw: 130,
      delta: -1.2,
      deltaGood: "down",
      sub: "7d",
      spark: [],
    },
  ],
  kpis: [
    {
      key: "recovered",
      label: "Total Dues Recovered",
      value: "₹1.2L",
      delta: 4.1,
      deltaGood: "up",
      spark: [],
    },
  ],
  recoveryTrend: [{ date: "2026-09-01", value: 1200 }],
  callVolumeStacked: [{ date: "2026-09-01", voice: 3, whatsapp: 1, chat: 0 }],
  sentimentDistribution: { positive: 50, neutral: 30, negative: 20 },
  botVsHuman: [],
  leaderboard: [
    { rank: 1, name: "Priya", team: "Delta", calls: 12, aht: "2m", upsell: 10, csat: 0.8 },
  ],
  atRiskAccounts: [
    {
      id: "c-1",
      name: "Anita",
      account: "AC-1",
      outstanding: 50000,
      daysPastDue: 21,
      risk: "high",
      lastContact: "2026-09-01",
      product: "Card",
    },
  ],
};

describe("dashboardToCsv", () => {
  it("includes KPIs, at-risk rows and the leaderboard", () => {
    const csv = dashboardToCsv(sample);
    expect(csv).toContain("kpi,recovered,Total Dues Recovered");
    expect(csv).toContain("at_risk,c-1,Anita,AC-1,50000,21,high");
    expect(csv).toContain("leaderboard,1,Priya,Delta,12");
    expect(csv).toContain("volume,2026-09-01,3,1,0");
  });
});

describe("dashboardFilename", () => {
  it("embeds the filters that produced the file", () => {
    expect(dashboardFilename({ range: "7d", segment: "card", team: "bot" })).toBe(
      "dashboard-7d-card-bot.csv",
    );
  });
});
