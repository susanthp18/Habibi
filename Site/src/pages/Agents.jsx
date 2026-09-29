import React from "react";
import { LiveCall } from "../components/LiveCall";
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
            An agent is a Voice Studio workflow: its voice, the tools it may call and the knowledge
            it may use, published as one version. Claude and other MCP clients can draft it. A
            person still publishes. The safety rails are not blocks on the canvas. They are checks
            the canvas cannot switch off.
          </>
        }
        secondary={{ label: "How decisions are made", href: "/decision-engine/" }}
        proof={[
          "Versioned agents",
          "Tools pinned to approved revisions",
          "Rehearsed before it dials",
          "Gated at publish",
        ]}
      />
      <Section
        eyebrow="The workflow"
        title={["A contract, checked", "at publish time."]}
        lede={
          <>
            Everything an agent is allowed to be lives in one published workflow. A new agent
            version goes through your change process: not a code deployment, and not a prompt
            somebody edited on a Friday.
          </>
        }
      >
        <Rows
          items={[
            [
              "Identity and voice",
              "Who the agent says it is and how it sounds, per language. The disclosure goes in the greeting, and the publish check warns when it is missing.",
            ],
            [
              "Tool grant",
              "The tools on each step of the workflow, each pinned to an approved revision. A revoked revision stops working even in the middle of a call.",
            ],
            [
              "Handoffs",
              "The named agents it may pass a live conversation to. The next agent brings its own workflow and tools, and gets a summary, not the previous agent's tool calls.",
            ],
            [
              "Drafts over MCP",
              "Claude, Cursor and other MCP clients can draft agents and tools with a personal, scoped key that expires within 90 days. Publishing, and approving tool revisions, stay with people in Voice Studio.",
            ],
            [
              "Release gate",
              "An agent cannot publish without approved identity-check and opt-out tools, and the gate blocks any account tool that could run before identity is verified.",
            ],
            [
              "Campaigns",
              "A published agent, a list and the pacing: concurrency, calls per second, retries, calling slots and a circuit breaker. Every number still passes the contact policy.",
            ],
          ]}
        />
      </Section>
      <Panel
        id="supervision"
        eyebrow="Supervision"
        title={["A person can step in", "without breaking the call."]}
        lede={
          <>
            From Floor command, a supervisor can listen to any live call, whisper a note to the
            agent, or take the call over and hand it back. Anyone without access to raw personal
            data hears and reads a masked version.
          </>
        }
      >
        <div className="supgrid">
          <div className="os">
            <div className="os__stack">
              {[
                ["Listen", "The live call and its transcript, as it happens."],
                [
                  "Whisper",
                  "A note to the agent mid-call. The customer never hears it, and AI can draft it.",
                ],
                [
                  "Take over",
                  "A person takes the call and can hand it back to the agent afterwards.",
                ],
                [
                  "Flags on every turn",
                  "Out-of-hours contact, account figures before identity, third-party disclosure and ignored opt-outs are flagged: on WhatsApp as each reply goes out, on calls as soon as the call is filed.",
                ],
              ].map(([name, body]) => (
                <div className="layer rise" data-fx key={name}>
                  <div className="layer__label">
                    <h3>{name}</h3>
                  </div>
                  <p className="layer__body">{body}</p>
                </div>
              ))}
            </div>
          </div>
          <LiveCall />
        </div>
      </Panel>
      <Section
        eyebrow="Channels"
        title={["One agent,", "voice and WhatsApp."]}
        lede="The same published agent answers calls and WhatsApp threads, with the same tools, the same identity rules and the same record."
      >
        <Cols
          items={[
            [
              "WhatsApp threads",
              "A transfer lands in the Conversation inbox. A person replies inside WhatsApp's 24-hour window and hands back, and the agent picks up with the last twelve messages.",
            ],
            [
              "Inbound calls",
              "The agent recognises the caller by number and answers general questions from the knowledge base. Account questions still need identity first.",
            ],
            [
              "Requests and leads",
              "Agents raise document requests for the Document desk, and leads for Upsell after an eligibility and consent re-check.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Placing the call"
        title={["The part most", "platforms get wrong."]}
        lede="Everything between deciding to call and somebody saying hello, where the compliance failures and most of the cost actually live. Every dial is recorded as an attempt, including the ones the contact policy refused."
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
              "Rotated, and a number that stops being answered is rested for a week.",
              "A number burned by spam labelling stops connecting. Answer rate is the cost base, so number health is an operating metric, not an afterthought.",
            ],
            [
              "Voicemail",
              "Set per agent: hang up, speak a short message, or play a recorded one. Call screeners are handled.",
              "Leaving a message, staying silent and hanging up are three different choices with three different costs.",
            ],
            [
              "Automated menus",
              "Detected, and the agent hangs up and logs it.",
              "Switchboards and carrier menus are machines. A language model guessing its way through them is expensive and unreliable.",
            ],
            [
              "Right-party contact",
              "Verified before any account detail: the last four digits on file, three tries, then lockout.",
              "An attempt that reaches the wrong person is fully paid for and worth nothing, and disclosing an account to them is a breach, not an inefficiency.",
            ],
            [
              "Third parties",
              "Refused, always.",
              "Contacting a family member or a reference to apply pressure is prohibited conduct. The voice engine will only ring the customer or your own allow-listed test handsets.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Inside the conversation"
        title={["Warm context,", "not cold discovery."]}
        lede={
          <>
            The agent opens the call already knowing the ledger, the last promise and why the
            payment failed, and the tools that read or change the account refuse to answer until the
            customer is verified. Discovery questions the system could have answered itself are how
            a collections call starts badly.
          </>
        }
      >
        <Steps
          items={[
            [
              "Identity and disclosure first",
              "Who is calling, on whose behalf, and that the call is recorded, before any account detail is spoken. A call that skips the disclosure is flagged.",
            ],
            [
              "The reason, captured as a field",
              "Forgot, salary timing, income loss, medical, a broken mandate, a disputed amount. After the call the reason is filed as one of nine codes, and that single field reprices a large share of the book: a message cures the forgot segment at a fraction of the cost of a call.",
            ],
            [
              "Out of policy goes to a person",
              "Voice agents have no waiver or settlement tool at all. A request outside policy transfers to a person, who gets the account packet, the limits and the disclosure checklist on screen.",
            ],
            [
              "The promise, made into an artefact",
              "Amount and date captured on the call, confirmed in writing with a pay link while the customer is still on the line, and a reminder on the day it falls due.",
            ],
            [
              "Language follows the customer",
              "If the caller switches language mid-call, speech recognition picks it up and the agent replies in that language, in a voice set up for it. Each agent can listen for up to ten languages, from a set that includes Hindi, Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati, Urdu and Arabic, alongside English.",
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
              "Two codes per attempt, one for how the connection went and one for what the conversation settled. Free-text wrap-up is a comment, never the record.",
            ],
            [
              "Written follow-up",
              "Confirmation of anything promised, sent within minutes on WhatsApp or SMS, with the payment link and without reading a URL aloud. Hardship, dispute and callback messages use fixed templates, never AI-written text.",
            ],
            [
              "Scheduled obligations",
              "Callbacks, document requests, disputes and leads land in shared queues with owners and SLA timers instead of a clerk's diary.",
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
              "Rehearse the workflow against scripted customer lines, with an AI customer playing the other side, and grade it against the agent's guardrails. A real call that went wrong becomes a check in one click, so the fix is proven before it is republished.",
            ],
            [
              "Publish gate",
              "It passes, or it lists exactly what blocks it. An agent with open warnings cannot go live on a routed channel, and if the gate cannot run, Publish stays disabled.",
            ],
            [
              "Versioned releases",
              "One live version per agent, each with a change note, and a release page showing how every version did on real calls: QA score, violations, calls where it spoke personal data. Rolling back publishes the old version as a new one, so history is never rewritten.",
            ],
          ]}
        />
        <Pull by="What changes for your compliance team">
          A new agent version is a change they can review, not a release they have to take on trust.
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
          ["/product/", "Every module", "Voice Studio, knowledge base, checks and agent routing."],
          ["/security/", "Deployment", "Your servers, your keys, your carrier."],
        ]}
      />
      <Closing
        title={["Hear one before", "you believe it."]}
        lede="We will build an agent against your policy in Voice Studio during the walkthrough, then try to make it say something it should not."
        secondary={{ label: "See the decision engine", href: "/decision-engine/" }}
      />
    </>
  );
}
