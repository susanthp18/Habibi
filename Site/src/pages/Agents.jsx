import React from "react";
import {
  Closing,
  Cols,
  Faq,
  More,
  PageHero,
  Panel,
  Pull,
  Rows,
  Section,
  Steps,
  Table,
} from "../components/ui";
import { faqs } from "../data/faqs";

export function AgentsPage() {
  return (
    <>
      <PageHero
        eyebrow="Agents"
        title={["Compose the agent.", "You cannot unbolt", "the safety."]}
        lede={
          <>
            An agent is a Voice Studio workflow: its voice, the tools it may call, and the knowledge
            it may use, published as one version. Claude and Codex can draft the workflow and the
            tools over MCP. A person still publishes. The compliance rails are not a component on
            the canvas. They are the floor the canvas sits on.
          </>
        }
        secondary={{
          label: "How decisions are made",
          href: "/decision-engine/",
        }}
        proof={[
          "Versioned Voice Studio agents",
          "Tools derived, never granted ad hoc",
          "Rehearsed before it dials",
          "Published behind gates",
        ]}
      />
      <Section
        eyebrow="The workflow"
        title={["A contract, checked", "at publish time."]}
        lede={
          <>
            Everything an agent is allowed to be lives in one published workflow. A new campaign is
            a version of that workflow going through your change process — not a code deployment,
            and not a prompt somebody edited on a Friday.
          </>
        }
      >
        <Rows
          items={[
            [
              "Identity and voice",
              "Who the agent says it is, which is also what the disclosure requirements are written against.",
            ],
            [
              "Tool grant",
              "The tools on the workflow. A revision is not callable on a live call until a person approves it, and it stays fixed until the next published release.",
            ],
            [
              "Handoffs",
              "The named agents it may transfer a live conversation to. The receiving agent brings its own workflow, and therefore its own tools.",
            ],
            [
              "Drafts over MCP",
              "Claude, Codex and similar tools can draft the workflow and the tools. Publishing the agent, and approving a tool revision, stay with a person in Voice Studio.",
            ],
            [
              "Locked engines",
              "The decision engines an author may not detach. The model proposes; a locked engine disposes; no workflow publishes without them.",
            ],
            [
              "Campaigns",
              "A reason to place calls with this agent: the objective, the definition of success, and the time it is allowed to take.",
            ],
          ]}
        />
      </Section>
      <Panel
        eyebrow="Permission"
        title={["The grant is derived.", "The offer is narrower."]}
        lede={
          <>
            What an agent may do is computed from its published workflow. What the model is shown on
            a given turn is a subset of that, chosen to keep the context small. The distinction
            matters because it means narrowing is always a cost decision and never a safety one — an
            offer can only ever be smaller than the grant, so a prompt-level mistake cannot widen
            what the agent is able to execute.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Grant",
                "The tools on the published workflow. Fixed until the next release. Auditable as a list.",
              ],
              [
                "Offer",
                "The subset placed in front of the model this turn. Always a subset. Never a superset.",
              ],
              [
                "Gate",
                "A publish-time check with three honest outcomes: pass, block, or skip. A gate never reports green for a check it did not run.",
              ],
              [
                "Reachability",
                "Whether traffic can arrive at an agent at all — as the entry agent, through a handoff, by direct address, or not at all. An unreachable agent is shown as unreachable rather than as healthy.",
              ],
            ].map(([f, a]) => (
              <div className="layer rise" data-fx key={f}>
                <div className="layer__label">
                  <h3>{f}</h3>
                </div>
                <p className="layer__body">{a}</p>
              </div>
            ))}
          </div>
        </div>
      </Panel>
      <Section
        eyebrow="Campaigns"
        title={["An objective,", "not a script."]}
        lede={
          <>
            A script says what to read. A campaign says what the calls are for, what would count as
            success, and how long they are allowed to take — which is what lets the same agent
            handle a customer who answers with something the script never anticipated.
          </>
        }
      >
        <Cols
          items={[
            [
              "The campaign",
              "One reason to place calls: the published agent, the definition of success, the time budget. A welcome call that prevents the first failure is worth more than any call after it.",
            ],
            [
              "The attempt",
              "The object everything is measured on. Every dial, whether or not anyone answers, with its outcome and its cost. Attempts per connect is the dominant term in the economics, and without this object it cannot be known.",
            ],
            [
              "The outcome",
              "What the conversation settled, as one code from a closed vocabulary. Post-call obligations and the follow-up cadence both read it, so free text is never the source of truth.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Placing the call"
        title={["The part most", "platforms get wrong."]}
        lede="Everything between deciding to call and somebody saying hello, where the compliance failures and most of the cost actually live."
        wide
      >
        <Table
          head={["Concern", "What PayInt does", "Why"]}
          rows={[
            [
              "Pacing",
              "Reserved-concurrency power dialling. Never predictive.",
              "Predictive dialling works by over-dialling and abandoning the surplus. An abandoned call to a customer in arrears is a conduct problem, and no efficiency gain is worth it.",
            ],
            [
              "Number pools",
              "Numbers rotated and rested, with per-number health tracked.",
              "A number burned by spam labelling stops connecting. Answer rate is the cost base, so number health is an operational metric, not an afterthought.",
            ],
            [
              "Voicemail",
              "A first-class action with its own decision.",
              "Leaving a message, staying silent and hanging up are three different choices with three different costs. Treating voicemail as a failed call throws away the distinction.",
            ],
            [
              "Automated menus",
              "Traversed deterministically where permitted.",
              "Switchboards and carrier menus are machines. A language model improvising through them is expensive and unreliable.",
            ],
            [
              "Right-party contact",
              "Verified before any account detail is spoken.",
              "An attempt that reaches the wrong person is fully paid for and worth zero — and disclosing an account to them is a breach, not an inefficiency.",
            ],
            [
              "Third parties",
              "Refused unless origination consent exists.",
              "Contacting a family member or reference to apply pressure is prohibited conduct. The gate sits before the number reaches the dialler.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Inside the conversation"
        title={["Warm context,", "not cold discovery."]}
        lede={
          <>
            The agent opens the call already knowing the ledger, the last promise, the reason the
            payment failed and what it is authorised to offer. Discovery questions the system could
            have answered itself are how a collections call starts badly.
          </>
        }
      >
        <Steps
          items={[
            [
              "Identity and disclosure first",
              "Who is calling, on whose behalf, why, and that the call is recorded — before any account detail is spoken. Missing disclosures are product bugs here, not training issues.",
            ],
            [
              "The reason, captured as a field",
              "Forgot, insufficient funds at the time, dispute, hardship, already paid. This single structured field reprices a large share of the book: a message cures the forgot segment at a fraction of the cost of the call that also cures it.",
            ],
            [
              "Negotiation inside a real envelope",
              "The authority matrix says yes, no, or up to this amount, and it says so before the agent speaks. Out-of-policy requests warm-transfer with the packet ready rather than dying as a promise to escalate.",
            ],
            [
              "The promise, made into an artefact",
              "Amount, date and channel captured from the turn, confirmed in writing within minutes, with a pay link and a reminder scheduled for the day it falls due.",
            ],
            [
              "Language follows the customer",
              "If the caller switches language mid-call, the agent follows in that language's own script and in a voice configured for it — Hindi, Tamil, Telugu and the other languages set on the agent.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="After the call"
        title={["The obligations", "close themselves."]}
        lede={
          <>
            After-call work is where a human floor loses a third of its capacity and where promises
            quietly die. Everything the conversation created becomes a scheduled obligation rather
            than a note somebody meant to write.
          </>
        }
      >
        <Rows
          items={[
            [
              "Structured disposition",
              "Derived from the turn itself. Free-text wrap-up is a comment, never the record that downstream systems read.",
            ],
            [
              "Written follow-up",
              "Confirmation of anything promised, sent within minutes on the channel the customer uses, with the payment link and without reading a URL aloud.",
            ],
            [
              "Scheduled obligations",
              "Reminders, callbacks, documents and dispute evidence enter queues that act on their own rather than waiting for a clerk.",
            ],
            [
              "Back into the engine",
              "Kept or broken is computed from the ledger. A break re-decides the next action that hour, under an attempt cap that makes the ladder stop.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Before it dials" title={["Rehearsed, gated,", "then published."]}>
        <Cols
          items={[
            [
              "Checks",
              "Rehearse the workflow against scripted customer lines and see what it does — including when the customer is angry, confused, or someone else entirely. A real call that went wrong becomes a check in one click, so the fix is proven before it is republished.",
            ],
            [
              "Publish gates",
              "Pass, block, or skip. A skipped check is reported as skipped, because a green light for a check that never ran is worse than a red one.",
            ],
            [
              "Versioned deployment",
              "One version of an agent is live in a given environment, and you can see which — and how each version did on real calls: QA score, violations, leaked personal data. Rolling back is selecting the previous version, not redeploying code.",
            ],
          ]}
        />
        <Pull by="What changes for your compliance team">
          A new campaign is a config publish they review, not a release they have to take somebody's
          word for.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What people ask", "about the agents."]}>
        <Faq items={faqs["/agents/"]} />
      </Section>
      <More
        links={[
          [
            "/compliance/",
            "Compliance and QA",
            "Every conversation scored, with the evidence behind each score.",
          ],
          ["/product/", "Every module", "Voice Studio, knowledge base, checks and routing."],
          ["/security/", "Deployment", "Your trunks, your models, your perimeter."],
        ]}
      />
      <Closing
        title={["Hear one before", "you believe it."]}
        lede="We will build an agent against your policy in Voice Studio during the walkthrough, then try to make it say something it should not."
        secondary={{
          label: "See the decision engine",
          href: "/decision-engine/",
        }}
      />
    </>
  );
}
