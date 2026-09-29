// FAQ entries per page, [question, answer]. Rendered on the page and emitted as
// FAQPage JSON-LD by scripts/prerender.mjs, so keep answers plain text.
export const faqs = {
  "/platform/": [
    [
      "Is PayInt a voice AI product?",
      "No. Voice is one channel. PayInt decides which accounts to work, on which channel, at what hour and under whose authority, then carries that decision out: by message, by voice, by a person, or by doing nothing at all. Positioned as a voice product, the most valuable behaviour in the system would be the one it punishes: not calling.",
    ],
    [
      "How long does an implementation take?",
      "PayInt reads your book through one contract for accounts, instalments, mandates, payments, consent and the contact ledger. Mapping your systems onto it is the long pole, usually four to six weeks. Agents, rules and scorecards are configuration, so they move at the speed of your compliance review, not ours.",
    ],
    [
      "Does it replace our collections CRM?",
      "It can, and most deployments let it. PayInt ships the queues a floor actually runs on (promises, disputes, callbacks, document requests and audit), so the alternative is a second system of record and a reconciliation problem. Where a CRM has to stay, PayInt sends it signed events for promises, disputes, payments and call outcomes.",
    ],
    [
      "What happens to our existing collectors?",
      "They stop dialling the early book and start taking the work that needs judgement: hardship, disputes, settlements and complaints. Those arrive with the transcript, the ledger and the account's limits already on screen.",
    ],
  ],
  "/decision-engine/": [
    [
      "How is uplift different from a propensity model?",
      "A propensity model ranks people by how likely they are to pay, which puts self-curers at the top: customers who would have paid anyway. Your most expensive capacity is then spent on people who needed nothing, and their payment is booked as the model's own success. Uplift ranks by the difference your action makes: the chance of cure if you act, minus the chance of cure if you do not.",
    ],
    [
      "Can the language model overrule the engine?",
      "No. There is no language model in scoring, policy or arbitration, and the build fails if someone adds one. Candidate actions are vetoed before they are scored, so a vetoed action cannot come back on a high score. A model can explain a decision afterwards, or propose a setting change for a person to approve.",
    ],
    [
      "Where do the probabilities come from on day one?",
      "From starting assumptions you can see and edit. Each night the engine re-learns reach and cure rates from real outcomes, and every decision shows whether a number came from this borrower's history, a learned rate, or the starting assumption.",
    ],
    [
      "Why is the score in money rather than a probability?",
      "Because a collections head can argue with a number in currency and cannot argue with 0.62. The score is exposure times recovery fraction, times the probability of reaching the customer and of resolving once reached, decayed by delay, minus cost and contact fatigue. Waiting scores exactly zero, so every action has to beat silence.",
    ],
    [
      "How do we know it is working, and not taking credit for self-cures?",
      "A randomised comparison group, and off-policy evaluation against logged decisions every week. The Is it working? view shows the extra cure rate against that group, and what is stopping contact, by reason. A challenger has to clear a promotion gate that refuses by default.",
    ],
  ],
  "/agents/": [
    [
      "Can an agent be given a tool by accident?",
      "No. Tools are pinned to approved revisions when the agent is published. A draft from an MCP client stays a draft until a person approves the tool revision and a person publishes the agent, and an admin approving their own revision is marked as a self-review.",
    ],
    [
      "What stops an agent promising something it should not?",
      "It has nothing to promise with. Voice agents have no waiver or settlement tool, so anything outside policy transfers to a person with the packet ready. What an agent can take is an amount and a date, confirmed in writing.",
    ],
    [
      "Can a supervisor step in on a live call?",
      "Yes. From Floor command a supervisor can listen, whisper a note to the agent, or take the call over and hand it back. Anyone without access to raw personal data hears and reads a masked version.",
    ],
    [
      "Can we test an agent before it dials a real customer?",
      "Yes. Checks rehearse it against scripted lines with an AI customer, and test calls to your allow-listed handsets go through every real check. Outbound calling stays off until an admin switches it on.",
    ],
    [
      "What languages are supported?",
      "The caller can switch language mid-call. Speech recognition identifies the language as they speak, and the agent replies in that language, in a voice set up for it. Each agent listens for up to ten languages, including Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Urdu and Arabic, alongside English.",
    ],
  ],
  "/compliance/": [
    [
      "Why is scoring every call different from doing more QA?",
      "Because sampling has a selection problem, not a volume problem. A floor that hears two to five per cent of its calls will usually not have heard the one that gets complained about. Scoring every conversation removes the sampling step rather than making it bigger.",
    ],
    [
      "Can an agent call outside permitted hours?",
      "No. The window is checked in the customer's time zone when the action is planned and again at the dial, on every path, including calls the voice engine starts itself. If the check cannot run, the call does not happen, and the refusal is recorded.",
    ],
    [
      "Does an AI model see raw customer data?",
      "The AI judge reads a masked transcript. Personal-data detection, intent, sentiment and beep timing run on four local models inside your deployment, with no internet access.",
    ],
    [
      "What does the auditor actually receive?",
      "One record per action: the rules in force at that moment, every rule consulted, the options considered and why each lost or was blocked, the recording and the transcript, with identity and card values already redacted for export.",
    ],
    [
      "Who is liable when an outsourced floor makes the call?",
      "You are, under every conduct regime we have deployed under. That is the argument for putting the gates in the platform rather than in agency training: a rule enforced before anything is dialled does not depend on whose floor it was.",
    ],
  ],
  "/security/": [
    [
      "Does any customer data leave our infrastructure?",
      "Records, recordings, transcripts and the evidence chain stay in your database and storage. Live calls use speech and language services on your own keys, in your chosen region, so audio and text go only to the provider you contract with. If that is not allowed, the voice engine can run on self-hosted models instead, scoped per deployment.",
    ],
    [
      "Can it run without cloud AI services?",
      "The post-call models already run locally with no internet access. For live calls, the voice engine can be pointed at self-hosted speech and language models. We scope that per deployment, because it changes the hardware you need.",
    ],
    [
      "Which telephony does it use?",
      "Yours to choose. The voice engine works with Twilio, Exotel, Plivo, Vobiz, Telnyx, Vonage and Cloudonix, or with your own Asterisk. WhatsApp runs on the WhatsApp Business Platform.",
    ],
    [
      "How do people sign in?",
      "With Microsoft Entra ID. There are no local passwords, guest and personal accounts are refused, and a first-time user gets no access until they are invited or approved.",
    ],
    [
      "Do you train on our data?",
      "The decision engine's models learn from your book inside your deployment. Cloud AI services run under your own agreement with the provider, on your keys, not ours.",
    ],
  ],
  "/pricing/": [
    [
      "Why not price per minute?",
      "Because the first observable effect of a working decision engine is a drop in call volume: it discovers that a large share of early-bucket dialling is worth less than silence. Priced per minute, the intelligence layer would cannibalise the revenue line. Priced per resolution, the same behaviour is the product.",
    ],
    [
      "Is there a per-seat licence?",
      "No. Seats are the wrong unit for a floor whose headcount should be falling on the early book while it holds steady on hardship and disputes.",
    ],
    [
      "What does a pilot cost?",
      "A fixed fee for thirty days on a defined slice of the book, with a comparison group and an audit pack on exit. If the lift is not attributable against that group, you have that in writing.",
    ],
  ],
  "/lenders/": [
    [
      "Where should voice agents not be used?",
      "Late buckets. Pre-due and early delinquency are coverage problems and suit automation; the middle is triage; distressed and legal accounts belong to a specialist. The engine reflects that: field visits only open up from 31 days past due and legal notices from 61, and as exposure rises it routes to people rather than dialling harder.",
    ],
    [
      "Do you work with our existing agencies?",
      'Yes. An agency\'s own dialler records can be loaded and checked against the same caps and calling window, and agency floors that run on PayInt use the same gates, rubric and evidence trail as your own. That is what turns "our vendor handled it" into something you can actually show.',
    ],
  ],
  "/insurance/": [
    [
      "What is available today?",
      "Everything on the lending side, including the contact policy, holds, suitability-gated offers and the evidence trail. Renewal, grace-period and revival workflows are being built with design partners, and we will say plainly which is which in a walkthrough.",
    ],
    [
      "Is this a separate product from the lending side?",
      "No, and that is the point. A customer late on an instalment and lapsing a policy is one cash-flow story. Two systems means two contact budgets, over-contact, and a hardship signal that neither side sees.",
    ],
    [
      "Can it sell on a renewal call?",
      "No. Offers are never spoken on a call. A signal from a conversation becomes an offer only after eligibility and suitability checks, and goes out later with marketing consent.",
    ],
  ],
};
