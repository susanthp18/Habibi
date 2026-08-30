export type SlaLevel = "ok" | "warn" | "breach";

export interface QueueRow {
  id: string;
  customer: string;
  accountId: string;
  type: string;
  detail: string;
  amount?: number;
  ageHours: number;
  sla: SlaLevel;
  slaLabel: string;
}

export const stats = {
  callsHandled: 31,
  callsHandledDelta: "+5 vs prior 7d",
  aht: "4m 22s",
  ahtDelta: "-38s vs team",
  resolutions: 24,
  resolutionRate: "77%",
  promisesCount: 8,
  promisesAmount: 18640,
};

export const disputes: QueueRow[] = [
  {
    id: "D-4821",
    customer: "Rahul Mehta",
    accountId: "AC-889123",
    type: "Payment already made",
    detail: "Claims UPI paid 12 Nov · ₹18,400",
    amount: 18400,
    ageHours: 3,
    sla: "warn",
    slaLabel: "1h 12m left",
  },
  {
    id: "D-4817",
    customer: "Anita Sharma",
    accountId: "AC-772044",
    type: "Late fee waiver",
    detail: "Requesting waiver — first default",
    amount: 950,
    ageHours: 8,
    sla: "ok",
    slaLabel: "6h 40m left",
  },
  {
    id: "D-4805",
    customer: "Kabir Singh",
    accountId: "AC-654321",
    type: "Incorrect EMI",
    detail: "EMI charged twice in Oct",
    amount: 7200,
    ageHours: 19,
    sla: "breach",
    slaLabel: "Overdue 42m",
  },
];

export const callbacks: QueueRow[] = [
  {
    id: "C-9911",
    customer: "Meera Iyer",
    accountId: "AC-441120",
    type: "Callback · 5:30 PM IST",
    detail: "Wants to discuss restructuring",
    ageHours: 1,
    sla: "ok",
    slaLabel: "In 1h 08m",
  },
  {
    id: "C-9908",
    customer: "Vikram Rao",
    accountId: "AC-330012",
    type: "Callback · 6:15 PM IST",
    detail: "Confirm PTP amount",
    ageHours: 2,
    sla: "warn",
    slaLabel: "In 1h 53m",
  },
];

export const docRequests: QueueRow[] = [
  {
    id: "R-2201",
    customer: "Priya Nair",
    accountId: "AC-556677",
    type: "Loan statement",
    detail: "FY 2024-25 · WhatsApp",
    ageHours: 4,
    sla: "ok",
    slaLabel: "20h left",
  },
  {
    id: "R-2198",
    customer: "Sanjay Gupta",
    accountId: "AC-880013",
    type: "NOC letter",
    detail: "Closed loan · Email",
    ageHours: 22,
    sla: "warn",
    slaLabel: "2h left",
  },
];

export const brokenPtps: QueueRow[] = [
  {
    id: "P-7712",
    customer: "Ravi Deshmukh",
    accountId: "AC-119988",
    type: "Broken PTP",
    detail: "Promised ₹22,000 on 18 Nov",
    amount: 22000,
    ageHours: 26,
    sla: "breach",
    slaLabel: "Follow up now",
  },
  {
    id: "P-7702",
    customer: "Sneha Kapoor",
    accountId: "AC-224466",
    type: "Partial PTP",
    detail: "Paid ₹5,000 of ₹15,000 promised",
    amount: 10000,
    ageHours: 9,
    sla: "warn",
    slaLabel: "Follow up today",
  },
];

export const nextLead = {
  id: "LD-1001",
  customer: "Vikram Rao",
  accountId: "AC-77410",
  productName: "Top-up Loan",
  amount: 150000,
  stage: "interested",
  window: "17:00–20:00",
  reason: "Highest-value open lead on your queue",
};

export const nextCallback = {
  customer: "Meera Iyer",
  accountId: "AC-441120",
  reason: "Discuss loan restructuring options",
  time: "5:30 PM",
  timezone: "IST",
  inMinutes: 68,
};

export const slaCountdowns = [
  {
    id: "D-4805",
    label: "Dispute · Kabir Singh",
    remaining: "Overdue 42m",
    level: "breach" as SlaLevel,
  },
  {
    id: "P-7712",
    label: "Broken PTP · Ravi Deshmukh",
    remaining: "26h since break",
    level: "breach" as SlaLevel,
  },
  {
    id: "R-2198",
    label: "NOC letter · Sanjay Gupta",
    remaining: "2h 04m left",
    level: "warn" as SlaLevel,
  },
];

export const outsideWindowCount = 1;
