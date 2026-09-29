// The product's modules, grouped as the app's sidebar groups them
// (Habibi/src/components/shell/Sidebar.tsx). Every "N modules" on the site is
// counted from this list, so a module added or retired in the app belongs here too.
export const moduleGroups = [
  {
    name: "Live operations",
    note: "What the floor is doing right now, on every channel at once.",
    items: [
      [
        "My workspace",
        "Your assigned work with SLA timers: disputes, callbacks, document requests, broken promises, follow-ups and leads, plus your last seven days in numbers.",
      ],
      [
        "Conversation inbox",
        "WhatsApp threads answered by your agent. A person can take over, reply inside the 24-hour window and hand the thread back.",
      ],
      [
        "Handoff hub",
        "The warm transfer, with the account packet open: balance, next instalment, last promise, open disputes, limits and the disclosure checklist.",
      ],
      [
        "Floor command",
        "Listen, whisper or take over a live call, and approve parked field, legal and servicing actions.",
      ],
    ],
  },
  {
    name: "CRM and resolution",
    note: "The account, its history, and every path to a cure.",
    items: [
      [
        "Executive dashboard",
        "Recovered amount, recovery rate, promises kept and time to first touch, from today to quarter to date, by segment and team.",
      ],
      [
        "Customer 360",
        "Ledger, instalments, promises, disputes, documents, notes and every interaction, with the next best action one click away.",
      ],
      [
        "Promise to pay",
        "Amount and date confirmed in writing with a pay link, revisions with a reason, and payment plans.",
      ],
      [
        "Disputes queue",
        "Already-paid claims and fee arguments as a queue. An open dispute stops collection pressure.",
      ],
      [
        "Document desk",
        "Requests for statements, no-dues letters, certificates and receipts, tracked by status, owner, SLA and delivery attempt.",
      ],
      [
        "Callbacks",
        "Call-me-after-payday as a scheduled obligation with an owner, not a diary line.",
      ],
      [
        "Upsell and leads",
        "Leads and opportunities from what customers said, checked for eligibility and suitability, and sent later only with marketing consent.",
      ],
      [
        "Decision intelligence",
        "Every decision with its options, vetoes and a plain-language explanation, measured against a comparison group.",
      ],
    ],
  },
  {
    name: "Compliance and QA",
    note: "Proof, on demand, for every action the platform took.",
    items: [
      [
        "Audit trail",
        "Every interaction with its recording, transcript, routing, flags and cost. Voice Studio calls carry a hash you can re-check.",
      ],
      [
        "Compliance risk",
        "Violation detection across the whole book, the rules that have no detector yet, and rule sets that need a second approver.",
      ],
      [
        "Consent and do-not-contact",
        "A hard gate on every outbound attempt: consent per channel and purpose, contact caps across channels, and the calling window.",
      ],
      [
        "Redaction and export",
        "Masked transcripts, a beeped copy of every recording and watermarked exports. The original only for roles cleared to hear it.",
      ],
      [
        "QA scorecards",
        "A scorecard for every conversation, each score showing what decided it and on what evidence, with calibration and coaching.",
      ],
      [
        "Bot analytics",
        "Containment, intents, sentiment and latency, by agent and by released version.",
      ],
    ],
  },
  {
    name: "Voice Studio",
    note: "Build, rehearse and release the voice and WhatsApp agents. Drafts can come from Claude or any MCP client; a person still publishes.",
    items: [
      [
        "Voice agents",
        "The workflow: voice, tools, knowledge and handoffs, published as one version.",
      ],
      [
        "Campaigns",
        "Dial a list with a published agent, with concurrency, retries and calling slots. Every number still passes the contact policy.",
      ],
      ["Agent runs", "Every call an agent handled, with its transcript, tool calls and cost."],
      [
        "Knowledge base",
        "Documents the agent may retrieve on a call. The same knowledge suggests replies in the inbox.",
      ],
      [
        "Call recordings",
        "Playback through the same redaction and access checks as the audit trail.",
      ],
      ["Audio library", "Pre-recorded prompts an agent can play instead of synthesising."],
      [
        "Tools",
        "What an agent may call. Each revision sets its risk, channels and the identity it needs, and a person approves it before it goes live.",
      ],
      [
        "Models",
        "Language, speech, voice and embedding providers on your own keys, with per-agent overrides.",
      ],
      ["Guardrails", "Prohibited phrases and per-agent rules, flagged on every call and chat."],
      ["Checks", "Scripted rehearsals of an agent before a real number is dialled."],
      [
        "Telephony",
        "Carrier accounts and numbers: Twilio, Exotel, Plivo, Vobiz, Telnyx, Vonage, Cloudonix or your own Asterisk.",
      ],
      [
        "Agent routing",
        "Which published agent takes each number, outbound objective and WhatsApp thread.",
      ],
      [
        "Releases",
        "Which version is live, how each version did on real calls, and rollbacks that add a version instead of rewriting one.",
      ],
      ["Reports", "Runs, transfers, outcomes and call length across agents, with CSV export."],
      ["Developers", "API keys for the voice engine."],
      [
        "Studio settings",
        "The MCP connection and personal keys, test phone number, time zone and tracing.",
      ],
      ["Help", "The Voice Studio guide, inside the product."],
    ],
  },
  {
    name: "Bot configuration",
    note: "The plumbing around the agents: what connects, what it costs, and who may see it.",
    items: [
      [
        "Webhooks",
        "Signed events out to your systems, switched on only after a review and a successful test delivery.",
      ],
      [
        "Billing and usage",
        "Model, speech and carrier spend by service and tenant, cost per resolved call, and budget rules that can pause outbound calling.",
      ],
      [
        "Roles and access",
        "Microsoft sign-ins, invites and access requests, and the permission matrix every module and export is checked against.",
      ],
      [
        "Settings",
        "Automation switches that stay off until an admin turns them on, plus test numbers and test calls.",
      ],
    ],
  },
];

export const moduleCount = moduleGroups.reduce((sum, group) => sum + group.items.length, 0);
