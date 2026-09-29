export const moduleGroups = [
  {
    name: "Live operations",
    note: "What the floor is doing right now, on every channel at once.",
    items: [
      ["My workspace", "The allocated list and shift stats, replacing the printed sheet."],
      ["Conversation inbox", "Inbound calls and messages, one thread per customer."],
      ["Handoff hub", "The warm transfer, with the transcript and the packet already open."],
      ["Floor command", "Listen, whisper, barge — the supervisor's walk-around, made live."],
    ],
  },
  {
    name: "CRM and resolution",
    note: "The account, its history, and every path to a cure.",
    items: [
      ["Executive dashboard", "Collection efficiency, roll-forward and promises kept, intra-day."],
      ["Customer 360", "Ledger, instalments, promises, documents, notes and every interaction."],
      ["Promise to pay", "Amount, date and channel, confirmed in writing with a pay link."],
      ["Disputes queue", "Already-paid claims and fee arguments as a queue, not a note."],
      ["Document desk", "Statements, no-dues letters and pay links generated, sent and retried."],
      ["Callbacks", "Call-me-after-payday as a scheduled obligation, not a diary line."],
      ["Upsell and leads", "A gated recommender that cannot pitch what the customer cannot have."],
      ["Decision intelligence", "The treatment engine: what to do next, on what channel, when."],
    ],
  },
  {
    name: "Compliance and QA",
    note: "Proof, on demand, for every action the platform took.",
    items: [
      [
        "Audit trail",
        "Recording, transcript, routing and flags for every contact, with a tamper-evident hash you can verify.",
      ],
      ["Compliance risk", "Violation detection across the whole book, not a sampled list."],
      [
        "Consent and do-not-contact",
        "A hard gate on every outbound attempt, counted from the ledger.",
      ],
      [
        "Redaction and export",
        "Masked transcripts and a beeped copy of every recording; the original only for roles cleared to hear it.",
      ],
      [
        "QA scorecards",
        "Every call graded against your rubric, each score showing who decided it and on what evidence.",
      ],
      [
        "Bot analytics",
        "Containment, intents, sentiment and latency, by agent and by released version.",
      ],
    ],
  },
  {
    name: "Voice Studio",
    note: "Build, rehearse and release the voice agents. Drafts can come from Claude or Codex; a person still publishes.",
    items: [
      [
        "Voice agents",
        "The workflow: voice, tools, knowledge and handoffs, published as one version.",
      ],
      ["Campaigns", "An objective, a success definition and a time budget for a published agent."],
      ["Agent runs", "Every call an agent handled, with its transcript, tool calls and cost."],
      ["Knowledge base", "Documents the agent may retrieve on a call."],
      [
        "Call recordings",
        "Playback through the same redaction and access checks as the audit trail.",
      ],
      ["Audio library", "Pre-recorded prompts an agent can play instead of synthesising."],
      ["Tools", "What an agent may call, each revision approved by a person before it goes live."],
      ["Models", "The speech, voice and language models each agent runs on."],
      ["Guardrails", "Per-agent rules every turn is checked against."],
      ["Checks", "Scripted rehearsals of an agent before a real number is dialled."],
      ["Telephony", "Your trunks and numbers."],
      [
        "Agent routing",
        "Which published agent takes each number, outbound objective and WhatsApp thread.",
      ],
      ["Releases", "Which version is live, and how each version did on real calls."],
      ["Reports", "Call volumes, outcomes and cost across agents."],
      ["Developers", "API keys and the MCP endpoint that drafts agents from Claude or Codex."],
      ["Studio settings", "Organisation preferences and the MCP server connection."],
      ["Help", "The Voice Studio guide, inside the product."],
    ],
  },
  {
    name: "Bot configuration",
    note: "The plumbing around the agents: who takes what, what connects, and who may see it.",
    items: [
      ["Routing and logic", "Which queue, agent or person takes each contact."],
      ["Integrations", "Core banking, loan management, CRM, warehouse and telephony."],
      ["Webhooks", "Events out to the systems that need to know."],
      ["Billing and usage", "Cost per resolved contact, by tenant and by service."],
      ["Roles and access", "Scope checks on every module and every export."],
      ["Settings", "Tenant-wide configuration."],
    ],
  },
];

export const moduleCount = moduleGroups.reduce((sum, group) => sum + group.items.length, 0);
