export const faqs = {
  "/platform/": [
    [
      "Is PayInt a voice AI product?",
      "No. Voice is one execution channel. PayInt decides which accounts to work, on which channel, at what hour and under whose authority, then executes that decision — by message, by voice, by a human agent, or by doing nothing at all. Positioned as a voice product, the most valuable behaviour in the system would be the one it punishes: not calling.",
    ],
    [
      "How long does an implementation take?",
      "The read path into your core banking and loan management systems is the long pole, and it is usually four to six weeks. Agents, policy and scorecards are configuration rather than code, so they move at the speed of your compliance review rather than ours.",
    ],
    [
      "Does it replace our collections CRM?",
      "It can, and most deployments let it. PayInt ships the queues a floor actually runs on — promises, disputes, callbacks, documents, audit — so the alternative is a second system of record and a reconciliation problem. Where a CRM has to stay, PayInt integrates and writes back.",
    ],
    [
      "What happens to our existing collectors?",
      "They stop dialling the early book and start taking the work that needs judgement: hardship, disputes, settlements and complaints. Those arrive with the transcript, the ledger and the authority envelope already on screen.",
    ],
  ],
  "/decision-engine/": [
    [
      "How is uplift different from a propensity model?",
      "A propensity model ranks people by how likely they are to pay, which puts self-curers at the top — customers who would have paid anyway. The most expensive capacity you have is then spent on people who needed nothing, and their payment is booked as the model's own success. Uplift ranks by the difference your action makes: the probability of cure if you act, minus the probability of cure if you do not.",
    ],
    [
      "Can the language model overrule the engine?",
      "No, and the ordering is an architectural boundary rather than a setting. Candidate actions are vetoed before they are scored, so a vetoed action cannot be resurrected by a high score. An optional re-ranker may reorder an already-approved shortlist and draft one line of rationale; it cannot introduce an action, change a channel or an instant, or state a figure that was not in the payload it was handed.",
    ],
    [
      "Why is the score in money rather than a probability?",
      "Because a collections head can argue with a number in currency and cannot argue with 0.62. The score is exposure times recovery fraction, times the probability of reaching the customer and of resolving once reached, decayed by delay, minus cost and contact fatigue. Waiting scores exactly zero, so every action has to beat silence.",
    ],
    [
      "How do we know it is working, and not taking credit for self-cures?",
      "A randomised control arm, and off-policy evaluation against logged propensities. A challenger has to clear a promotion gate that refuses by default. If the lift is not attributable, the gate does not open.",
    ],
  ],
  "/agents/": [
    [
      "Can an agent be given a tool by accident?",
      "No. Tools belong to the workflow, and a revision is not callable on a live call until a person approves it. A draft from Claude or Codex over MCP is not live until that approval, and until a person publishes the agent.",
    ],
    [
      "What stops an agent promising something it should not?",
      "The authority matrix. Goodwill inside policy can close on the call; anything outside it warm-transfers to a specialist with the packet ready, and the agent never quotes a number. Waivers and settlement percentages are not decisions the model is allowed to reach.",
    ],
    [
      "Can we test an agent before it dials a real customer?",
      "Yes. Checks rehearse the workflow against scripted customer lines before a real number is dialled, and publishing runs a set of gates with three honest outcomes: pass, block or skip. A gate never reports green for a check it did not run.",
    ],
    [
      "What languages are supported?",
      "The caller can switch language mid-call. Speech recognition identifies the language on each phrase, and the agent replies in that language's own script, in a voice configured for it. The set includes Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Urdu and Arabic, alongside English.",
    ],
  ],
  "/compliance/": [
    [
      "Why is scoring every call different from doing more QA?",
      "Because sampling has a selection problem, not a volume problem. A floor that hears two to five per cent of its calls will usually not have heard the one that gets complained about. Scoring every conversation removes the sampling step rather than making it bigger.",
    ],
    [
      "Can an agent call outside permitted hours?",
      "The attempt is refused before it exists. Calling windows, do-not-contact status, frequency caps across every channel, origination consent and third-party contact are vetoes evaluated when the action is planned, not warnings raised after the fact.",
    ],
    [
      "What does the auditor actually receive?",
      "One record per action, carrying the policy version in force at that instant, the gate results, the score behind the decision, the number it came from, the recording and the transcript — with identity and card values already redacted for export.",
    ],
    [
      "Who is liable when an outsourced floor makes the call?",
      "You are, under every conduct regime we have deployed under. That is the argument for putting the gates in the platform rather than in agency training: a rule that is enforced before an attempt exists does not depend on whose floor it was.",
    ],
  ],
  "/security/": [
    [
      "Does any customer data leave our infrastructure?",
      "No. In the standard deployment the models, recordings, transcripts, embeddings and customer records all sit inside your perimeter, and there is no scoring round trip to a vendor cloud because there is no vendor cloud in the path.",
    ],
    [
      "Can it run air-gapped?",
      "Yes. Updates arrive as signed bundles your team reviews and applies on your own change-control schedule.",
    ],
    [
      "Which telephony does it use?",
      "Yours. Voice runs on your SIP or PSTN trunks rather than a managed cloud voice provider, which is what keeps the recordings and the numbering inside your contracts.",
    ],
    [
      "How are models updated without sending you our data?",
      "Model weights ship to you; your data does not ship to us. Anything learned from your book stays in your deployment unless you sign a separate agreement saying otherwise.",
    ],
  ],
  "/pricing/": [
    [
      "Why not price per minute?",
      "Because the first observable effect of a working decision engine is a drop in call volume — it discovers that a large share of early-bucket dialling is worth less than silence. Priced per minute, the intelligence layer would cannibalise the revenue line. Priced per resolution, the same behaviour is the product.",
    ],
    [
      "Is there a per-seat licence?",
      "No. Seats are the wrong unit for a floor whose headcount should be falling on the early book while it holds steady on hardship and disputes.",
    ],
    [
      "What does a pilot cost?",
      "A fixed fee for thirty days on a defined slice of the book, with a held-out control group and an audit pack on exit. If the lift is not attributable against the control, you have that in writing.",
    ],
  ],
  "/lenders/": [
    [
      "Where should voice agents not be used?",
      "Late buckets. Pre-due and early delinquency are coverage problems and suit automation; the middle is triage; distressed and legal accounts belong to a specialist. The engine reflects that — as exposure and days past due rise, it routes to people rather than dialling harder.",
    ],
    [
      "Do you work with our existing agencies?",
      'Yes, and multi-tenant audit is how that stays defensible. Each agency floor gets its own policy set and its own evidence trail, which is what turns "our vendor handled it" into something you can actually show.',
    ],
  ],
  "/insurance/": [
    [
      "Is this a separate product from the lending side?",
      "No, and that is the point. A customer late on an instalment and lapsing a policy is one cash-flow story. Two systems means two contact budgets, over-contact, and a hardship signal that neither side sees.",
    ],
    [
      "Can it sell on a renewal call?",
      "Only inside a suitability gate. The recommender cannot pitch a product the customer is not eligible for, and collection conversations are kept separate from cross-sell by policy rather than by agent discipline.",
    ],
  ],
};
