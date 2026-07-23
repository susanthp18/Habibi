export type Channel = "whatsapp" | "sms" | "email";
export type Sender = "customer" | "bot" | "agent";
/** Stored conversation status — "mine" is derived (assignedUserId === me). */
export type ThreadStatus = "bot" | "needs_human" | "escalated" | "assigned";
export type SlaLevel = "ok" | "warn" | "breach";
export type Sentiment = "positive" | "neutral" | "negative";
export type DeliveryStatus = "sent" | "delivered" | "read";

export interface Message {
  id: string;
  sender: Sender;
  text: string;
  time: string; // "3:41 PM"
  delivery?: DeliveryStatus; // for bot/agent
}

export interface SystemEvent {
  id: string;
  kind: "system";
  text: string;
  time: string;
}

export type ThreadItem = Message | SystemEvent;

export interface ThreadContext {
  riskLevel: "High" | "Medium" | "Low";
  contactableNow: boolean;
  contactWindow: string;
  outstanding: number;
  outstandingAging: string;
  nextEmiDate: string;
  nextEmiAmount: number;
  lastPromise: {
    amount: number;
    date: string;
    status: "Kept" | "Broken" | "Pending" | "Partial";
  } | null;
  openDisputes: { id: string; summary: string }[];
  recentInteractions: {
    id: string;
    kind: "call" | "chat";
    summary: string;
    when: string;
    sentiment: Sentiment;
  }[];
}

export interface Thread {
  id: string;
  customer: string;
  /** CRM customer id for Customer 360 / PTP / dispute deep-links. */
  customerId?: string;
  accountId: string;
  channel: Channel;
  status: ThreadStatus;
  /** Owning agent; Mine filter = assignedUserId === current user. */
  assignedUserId: string | null;
  isMine: boolean;
  /** True while a bot turn is queued/running (WhatsApp auto-reply in flight). */
  botTyping?: boolean;
  sla: SlaLevel;
  unread: number;
  lastTime: string;
  lastPreview: string;
  lastFrom: Sender;
  sentiment: Sentiment;
  ragSuggestions: string[];
  /** Optional grounded draft from shared kb_retrieve (same as Test Retrieval). */
  ragDraftAnswer?: string | null;
  messages: ThreadItem[];
  context: ThreadContext;
}

export const cannedResponses = [
  {
    id: "c1",
    label: "Greeting",
    text: "Hi, this is Priya from HDFC Collections. How can I help you today?",
  },
  {
    id: "c2",
    label: "Verify identity",
    text: "For your security, can you confirm your registered date of birth and the last 4 digits of your account?",
  },
  {
    id: "c3",
    label: "Payment link",
    text: "I'm sending you a secure payment link now. It's valid for the next 30 minutes.",
  },
  {
    id: "c4",
    label: "Late-fee waiver policy",
    text: "As a first-time waiver, we can apply a one-time reversal of ₹500 on the late fee. Would you like me to raise the request?",
  },
  {
    id: "c5",
    label: "Escalation notice",
    text: "I understand your concern. I'm escalating this to my supervisor and someone will reach out within 24 hours.",
  },
];

export const threads: Thread[] = [
  {
    id: "t1",
    customer: "Rahul Mehta",
    customerId: "rahul-sinha",
    accountId: "AC-889123",
    channel: "whatsapp",
    status: "needs_human",
    assignedUserId: null,
    isMine: false,
    sla: "warn",
    unread: 2,
    lastTime: "3:41 PM",
    lastPreview: "I already paid this on 12 Nov via UPI. Why is it showing due?",
    lastFrom: "customer",
    sentiment: "negative",
    ragSuggestions: [
      "Late-fee waiver policy (first-time)",
      "How to raise a payment-not-reflected dispute",
      "UPI reconciliation SLA",
    ],
    messages: [
      { id: "m1", sender: "bot", text: "Hi Rahul, this is HDFC Collections Assistant. I see an outstanding of ₹18,400 on account ending 9123. How can I help?", time: "3:32 PM", delivery: "read" },
      { id: "m2", sender: "customer", text: "I already paid this on 12 Nov via UPI.", time: "3:34 PM" },
      { id: "m3", sender: "bot", text: "Thanks for letting me know. Could you share the UPI reference number so I can check?", time: "3:34 PM", delivery: "read" },
      { id: "m4", sender: "customer", text: "It was 4429871122. Please check.", time: "3:36 PM" },
      { id: "m5", sender: "bot", text: "I can see a pending reconciliation for that reference. I'm capturing this as a dispute so a specialist can review.", time: "3:37 PM", delivery: "read" },
      { id: "s1", kind: "system", text: "Bot captured dispute D-4821 · flagged for human review", time: "3:38 PM" },
      { id: "m6", sender: "customer", text: "Why is it showing due? This is frustrating.", time: "3:41 PM" },
      { id: "m7", sender: "customer", text: "Please fix this quickly.", time: "3:41 PM" },
    ],
    context: {
      riskLevel: "Medium",
      contactableNow: true,
      contactWindow: "9 AM – 7 PM IST",
      outstanding: 18400,
      outstandingAging: "8 days overdue",
      nextEmiDate: "01 Dec 2025",
      nextEmiAmount: 18400,
      lastPromise: null,
      openDisputes: [{ id: "D-4821", summary: "Payment already made (UPI)" }],
      recentInteractions: [
        { id: "i1", kind: "call", summary: "Inbound · dues query resolved by bot", when: "2d ago", sentiment: "neutral" },
        { id: "i2", kind: "chat", summary: "EMI schedule request", when: "5d ago", sentiment: "positive" },
      ],
    },
  },
  {
    id: "t2",
    customer: "Anita Sharma",
    customerId: "anita-desai",
    accountId: "AC-772044",
    channel: "whatsapp",
    status: "bot",
    assignedUserId: null,
    isMine: false,
    sla: "ok",
    unread: 0,
    lastTime: "3:29 PM",
    lastPreview: "Thanks, that's all I needed for now.",
    lastFrom: "customer",
    sentiment: "positive",
    ragSuggestions: [
      "Late-fee waiver eligibility",
      "How to enable auto-debit",
    ],
    messages: [
      { id: "m1", sender: "customer", text: "Hi, I want to know if my late fee can be waived this month.", time: "3:20 PM" },
      { id: "m2", sender: "bot", text: "Hi Anita — since this is your first late payment in 12 months, you're eligible for a one-time waiver of ₹500. Should I raise the waiver request?", time: "3:21 PM", delivery: "read" },
      { id: "m3", sender: "customer", text: "Yes please.", time: "3:22 PM" },
      { id: "m4", sender: "bot", text: "Waiver request raised. You'll see the reversal in 2 business days. Anything else?", time: "3:22 PM", delivery: "read" },
      { id: "m5", sender: "customer", text: "Thanks, that's all I needed for now.", time: "3:29 PM" },
    ],
    context: {
      riskLevel: "Low",
      contactableNow: true,
      contactWindow: "9 AM – 7 PM IST",
      outstanding: 950,
      outstandingAging: "3 days overdue",
      nextEmiDate: "05 Dec 2025",
      nextEmiAmount: 12500,
      lastPromise: { amount: 12500, date: "05 Nov 2025", status: "Kept" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "Late-fee waiver granted", when: "just now", sentiment: "positive" },
      ],
    },
  },
  {
    id: "t3",
    customer: "Kabir Singh",
    customerId: "james-patel",
    accountId: "AC-654321",
    channel: "email",
    status: "escalated",
    assignedUserId: null,
    isMine: false,
    sla: "breach",
    unread: 5,
    lastTime: "2:58 PM",
    lastPreview: "This is unacceptable — I want to speak with a manager immediately.",
    lastFrom: "customer",
    sentiment: "negative",
    ragSuggestions: [
      "Escalation script — manager callback",
      "Duplicate EMI charge reversal SLA",
      "Compliance disclosure template",
    ],
    messages: [
      { id: "m1", sender: "customer", text: "You have charged my EMI twice in October. Fix it.", time: "2:41 PM" },
      { id: "m2", sender: "bot", text: "I'm sorry to hear that. I can see two debits of ₹7,200 on 05 Oct and 07 Oct. I'm capturing this as a billing dispute now.", time: "2:42 PM", delivery: "read" },
      { id: "s1", kind: "system", text: "Bot escalated to human · reason: repeat charge", time: "2:44 PM" },
      { id: "m3", sender: "customer", text: "I've been a customer for 8 years. This is unacceptable.", time: "2:50 PM" },
      { id: "m4", sender: "customer", text: "I want to speak with a manager immediately.", time: "2:58 PM" },
    ],
    context: {
      riskLevel: "High",
      contactableNow: true,
      contactWindow: "8 AM – 8 PM IST",
      outstanding: 7200,
      outstandingAging: "Under dispute",
      nextEmiDate: "05 Dec 2025",
      nextEmiAmount: 7200,
      lastPromise: { amount: 7200, date: "05 Oct 2025", status: "Broken" },
      openDisputes: [{ id: "D-4805", summary: "Duplicate EMI charge · Oct" }],
      recentInteractions: [
        { id: "i1", kind: "call", summary: "Inbound · escalated, sentiment declining", when: "20m ago", sentiment: "negative" },
        { id: "i2", kind: "chat", summary: "Statement request fulfilled", when: "6d ago", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t4",
    customer: "Meera Iyer",
    customerId: "farah-ahmed",
    accountId: "AC-441120",
    channel: "whatsapp",
    status: "assigned",
    assignedUserId: "priya-nair",
    isMine: true,
    sla: "ok",
    unread: 0,
    lastTime: "1:14 PM",
    lastPreview: "You: Great, I'll call you at 5:30 PM sharp.",
    lastFrom: "agent",
    sentiment: "positive",
    ragSuggestions: [
      "Restructuring options — retail loan",
      "Callback scheduling policy",
    ],
    messages: [
      { id: "m1", sender: "customer", text: "Can someone call me later today to discuss restructuring?", time: "1:02 PM" },
      { id: "m2", sender: "bot", text: "Absolutely. When works best for you?", time: "1:02 PM", delivery: "read" },
      { id: "m3", sender: "customer", text: "5:30 PM if possible.", time: "1:05 PM" },
      { id: "s1", kind: "system", text: "You took over from bot · 1:10 PM", time: "1:10 PM" },
      { id: "m4", sender: "agent", text: "Hi Meera, Priya here from HDFC. I've scheduled your callback for today 5:30 PM IST.", time: "1:12 PM", delivery: "read" },
      { id: "m5", sender: "customer", text: "Perfect, thank you.", time: "1:13 PM" },
      { id: "m6", sender: "agent", text: "Great, I'll call you at 5:30 PM sharp.", time: "1:14 PM", delivery: "delivered" },
    ],
    context: {
      riskLevel: "Medium",
      contactableNow: true,
      contactWindow: "9 AM – 8 PM IST",
      outstanding: 46000,
      outstandingAging: "12 days overdue",
      nextEmiDate: "10 Dec 2025",
      nextEmiAmount: 15300,
      lastPromise: { amount: 15000, date: "20 Nov 2025", status: "Pending" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "Callback scheduled 5:30 PM", when: "just now", sentiment: "positive" },
        { id: "i2", kind: "call", summary: "Inbound · discussed restructuring", when: "1w ago", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t5",
    customer: "Priya Nair",
    customerId: "neha-kapoor",
    accountId: "AC-556677",
    channel: "whatsapp",
    status: "bot",
    assignedUserId: null,
    isMine: false,
    sla: "ok",
    unread: 0,
    lastTime: "12:48 PM",
    lastPreview: "Bot: I've sent the FY 2024-25 statement to your WhatsApp.",
    lastFrom: "bot",
    sentiment: "neutral",
    ragSuggestions: ["Statement password format", "Resend statement flow"],
    messages: [
      { id: "m1", sender: "customer", text: "Please send my loan statement for last financial year.", time: "12:45 PM" },
      { id: "m2", sender: "bot", text: "Sure — sharing the FY 2024-25 statement now.", time: "12:46 PM", delivery: "read" },
      { id: "s1", kind: "system", text: "Document sent · loan-statement-FY24-25.pdf", time: "12:47 PM" },
      { id: "m3", sender: "bot", text: "I've sent the FY 2024-25 statement to your WhatsApp.", time: "12:48 PM", delivery: "delivered" },
    ],
    context: {
      riskLevel: "Low",
      contactableNow: true,
      contactWindow: "9 AM – 7 PM IST",
      outstanding: 0,
      outstandingAging: "Up to date",
      nextEmiDate: "15 Dec 2025",
      nextEmiAmount: 22000,
      lastPromise: { amount: 22000, date: "15 Nov 2025", status: "Kept" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "Statement delivered on WhatsApp", when: "just now", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t6",
    customer: "Sanjay Gupta",
    customerId: "vikram-rao",
    accountId: "AC-880013",
    channel: "email",
    status: "needs_human",
    assignedUserId: null,
    isMine: false,
    sla: "warn",
    unread: 1,
    lastTime: "11:32 AM",
    lastPreview: "I need the NOC urgently for a home loan application.",
    lastFrom: "customer",
    sentiment: "neutral",
    ragSuggestions: ["NOC generation SLA", "Closed-loan NOC template"],
    messages: [
      { id: "m1", sender: "customer", text: "I closed my personal loan last month. Need the NOC letter.", time: "11:20 AM" },
      { id: "m2", sender: "bot", text: "Your loan closure is confirmed on 22 Oct. NOC generation takes up to 3 business days.", time: "11:22 AM", delivery: "read" },
      { id: "m3", sender: "customer", text: "I need the NOC urgently for a home loan application.", time: "11:32 AM" },
    ],
    context: {
      riskLevel: "Low",
      contactableNow: true,
      contactWindow: "9 AM – 7 PM IST",
      outstanding: 0,
      outstandingAging: "Loan closed",
      nextEmiDate: "—",
      nextEmiAmount: 0,
      lastPromise: null,
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "NOC request captured", when: "1h ago", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t7",
    customer: "Ravi Deshmukh",
    customerId: "anita-desai",
    accountId: "AC-119988",
    channel: "sms",
    status: "needs_human",
    assignedUserId: null,
    isMine: false,
    sla: "breach",
    unread: 1,
    lastTime: "10:04 AM",
    lastPreview: "Sorry, I couldn't pay yesterday. Can we do next week?",
    lastFrom: "customer",
    sentiment: "neutral",
    ragSuggestions: ["Broken PTP follow-up script", "Installment plan builder"],
    messages: [
      { id: "m1", sender: "bot", text: "Hi Ravi, this is a reminder that your promise of ₹22,000 was due yesterday. Have you made the payment?", time: "10:02 AM", delivery: "delivered" },
      { id: "m2", sender: "customer", text: "Sorry, I couldn't pay yesterday. Can we do next week?", time: "10:04 AM" },
    ],
    context: {
      riskLevel: "High",
      contactableNow: true,
      contactWindow: "10 AM – 6 PM IST",
      outstanding: 22000,
      outstandingAging: "Broken PTP · 26h",
      nextEmiDate: "01 Dec 2025",
      nextEmiAmount: 11000,
      lastPromise: { amount: 22000, date: "18 Nov 2025", status: "Broken" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "call", summary: "Inbound · promised ₹22,000 by 18 Nov", when: "3d ago", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t8",
    customer: "Sneha Kapoor",
    customerId: "neha-kapoor",
    accountId: "AC-224466",
    channel: "whatsapp",
    status: "bot",
    assignedUserId: null,
    isMine: false,
    sla: "warn",
    unread: 0,
    lastTime: "9:47 AM",
    lastPreview: "Bot: Would you like to hear about our debt-consolidation offer?",
    lastFrom: "bot",
    sentiment: "positive",
    ragSuggestions: ["Debt consolidation eligibility", "Upsell disclosure script"],
    messages: [
      { id: "m1", sender: "customer", text: "I paid ₹5,000 today.", time: "9:40 AM" },
      { id: "m2", sender: "bot", text: "Thanks Sneha — I can see the ₹5,000 partial payment. That leaves ₹10,000 remaining from your promise.", time: "9:41 AM", delivery: "read" },
      { id: "m3", sender: "customer", text: "Yes, I'll pay the rest next week.", time: "9:43 AM" },
      { id: "m4", sender: "bot", text: "Noted — I've updated your promise. Since you're paying regularly, would you like to hear about our debt-consolidation offer?", time: "9:47 AM", delivery: "delivered" },
    ],
    context: {
      riskLevel: "Medium",
      contactableNow: true,
      contactWindow: "9 AM – 7 PM IST",
      outstanding: 10000,
      outstandingAging: "Partial PTP",
      nextEmiDate: "08 Dec 2025",
      nextEmiAmount: 8500,
      lastPromise: { amount: 15000, date: "15 Nov 2025", status: "Partial" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "Upsell offer presented", when: "just now", sentiment: "positive" },
      ],
    },
  },
  {
    id: "t9",
    customer: "Vikram Rao",
    customerId: "vikram-rao",
    accountId: "AC-330012",
    channel: "whatsapp",
    status: "bot",
    assignedUserId: null,
    isMine: false,
    sla: "ok",
    unread: 0,
    lastTime: "Yesterday",
    lastPreview: "Bot: Your next EMI of ₹9,200 is due on 28 Nov.",
    lastFrom: "bot",
    sentiment: "neutral",
    ragSuggestions: ["EMI reminder script"],
    messages: [
      { id: "m1", sender: "customer", text: "When is my next EMI due?", time: "6:12 PM" },
      { id: "m2", sender: "bot", text: "Your next EMI of ₹9,200 is due on 28 Nov.", time: "6:12 PM", delivery: "read" },
    ],
    context: {
      riskLevel: "Low",
      contactableNow: false,
      contactWindow: "9 AM – 6 PM IST",
      outstanding: 0,
      outstandingAging: "Up to date",
      nextEmiDate: "28 Nov 2025",
      nextEmiAmount: 9200,
      lastPromise: { amount: 9200, date: "28 Oct 2025", status: "Kept" },
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "chat", summary: "EMI schedule query", when: "1d ago", sentiment: "neutral" },
      ],
    },
  },
  {
    id: "t10",
    customer: "Aarav Khanna",
    customerId: "james-patel",
    accountId: "AC-771122",
    channel: "sms",
    status: "escalated",
    assignedUserId: null,
    isMine: false,
    sla: "breach",
    unread: 3,
    lastTime: "Yesterday",
    lastPreview: "Stop calling me. I've asked twice already.",
    lastFrom: "customer",
    sentiment: "negative",
    ragSuggestions: ["DND opt-out capture", "Regulatory disclosure — RBI"],
    messages: [
      { id: "m1", sender: "bot", text: "Hi Aarav, this is a reminder about your overdue amount of ₹34,500.", time: "5:00 PM", delivery: "delivered" },
      { id: "m2", sender: "customer", text: "Stop contacting me on SMS.", time: "5:02 PM" },
      { id: "s1", kind: "system", text: "Bot detected DND request · escalated to human", time: "5:03 PM" },
      { id: "m3", sender: "customer", text: "Stop calling me. I've asked twice already.", time: "5:14 PM" },
    ],
    context: {
      riskLevel: "High",
      contactableNow: false,
      contactWindow: "DND requested on SMS",
      outstanding: 34500,
      outstandingAging: "18 days overdue",
      nextEmiDate: "01 Dec 2025",
      nextEmiAmount: 11500,
      lastPromise: null,
      openDisputes: [],
      recentInteractions: [
        { id: "i1", kind: "call", summary: "Inbound · customer angry", when: "3d ago", sentiment: "negative" },
      ],
    },
  },
];
