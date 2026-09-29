import React from "react";
import {
  Closing,
  Cols,
  Faq,
  Metrics,
  More,
  PageHero,
  Panel,
  Pull,
  Rows,
  Section,
  Table,
} from "../components/ui";
import { faqs } from "../data/faqs";

export function CompliancePage() {
  return (
    <>
      <PageHero
        eyebrow="Compliance and QA"
        title={["Sampling is not", "monitoring."]}
        lede={
          <>
            A floor that listens to two to five per cent of its calls has not heard the one that
            gets complained about. PayInt scores every conversation, refuses contact that would
            breach a rule before the attempt exists, and leaves one record per action that answers
            the question an auditor actually asks.
          </>
        }
        secondary={{
          label: "Deployment and security",
          href: "/security/",
        }}
        proof={[
          "Every call and message scored",
          "Gates before the attempt",
          "Recordings beeped over the PII",
          "Tamper-evident record",
        ]}
      />
      <Section
        eyebrow="The gap"
        title={["The call that matters", "is not in the sample."]}
        lede={
          <>
            Quality assurance by sampling has a selection problem, not a volume problem. On a large
            floor, tens of thousands of conversations a day are never heard by anyone — and the one
            that reaches a regulator is, by construction, unlikely to be among the few that were.
          </>
        }
      >
        <Metrics
          items={[
            {
              n: "2–5%",
              k: "Of calls a human QA function typically hears",
              note: "Industry-typical sampling rate. Everything outside it is unreviewed by definition, including the complaint you will have to answer for.",
            },
            {
              n: "100%",
              k: "Of conversations scored by PayInt",
              note: "A product property rather than an average: there is no sampling path in the runtime.",
            },
            {
              n: "Minutes",
              k: "From hang-up to a scored, redacted record",
              note: "Masking, the beeped recording and the scorecard are produced inside your perimeter. A language model is asked only about the criteria the rules and small models could not settle.",
            },
            {
              n: "0",
              k: "Attempts placed outside the permitted window",
              note: "Enforced when the action is planned and again when it is executed, and logged both times.",
            },
          ]}
        />
      </Section>
      <Panel
        eyebrow="Hard gates"
        title={["A rule you can turn off", "is not a rule."]}
        lede={
          <>
            Conduct requirements are implemented as vetoes evaluated before an action exists, not as
            guidance shown to an agent who is being measured on conversion. Nothing downstream can
            weigh them against a target, because nothing downstream ever sees the vetoed option.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Calling window",
                "Time-zone aware, and applied to the planned instant. Conversations in progress conclude before the cutoff rather than being cut off.",
              ],
              [
                "Do-not-contact",
                "Registry status and in-call opt-out, honoured across every channel within hours, counted from the ledger rather than from a counter somebody increments.",
              ],
              [
                "Frequency",
                "One cap across voice and messaging together. Capping per channel is how a floor makes persistent contact accidentally.",
              ],
              [
                "Consent",
                "Purpose-bound, captured at origination. A promotional message needs a different basis from a transactional one, and the difference is recorded.",
              ],
              [
                "Third-party contact",
                "Refused unless origination consent covers it. A warm transfer to a human does not silently unlock a guarantor's number.",
              ],
              [
                "Authority",
                "Waivers and settlement percentages sit outside what any agent may reach. In-policy goodwill can close on the call; the rest transfers with a packet.",
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
        eyebrow="Where the failures happen"
        title={["The violations", "a floor actually has."]}
        lede={
          <>
            These are the categories that show up in audits of human collections floors. Each one is
            a discipline problem when it lives in training, and a solved problem when it lives in
            the platform.
          </>
        }
        wide
      >
        <Table
          head={["Category", "On a human floor", "In the platform"]}
          rows={[
            [
              "Calls outside permitted hours",
              "A recurring finding, dependent on dialler configuration and agent discipline",
              "Refused at planning time; the attempt is never created",
            ],
            [
              "Missing or partial disclosure",
              "Varies by agent, by script version and by how the day is going",
              "Part of the flow, and scored on every conversation",
            ],
            [
              "Frequency and persistent contact",
              "Capped per channel, if at all, so the combined total is nobody's number",
              "One cross-channel cap, enforced before each attempt",
            ],
            [
              "Unauthorised third-party contact",
              "Hard to detect after the fact, easy to do under pressure",
              "Gated on origination consent before a number reaches the dialler",
            ],
            [
              "Recording coverage",
              "Partial, with gaps that surface exactly when they matter",
              "Complete, with the transcript attached to the same record",
            ],
            [
              "Pressure, intimidation, false statements",
              "Caught only if the call was in the sample",
              "Scored on every conversation, with the turn that proves it attached to the score",
            ],
          ]}
          caption="The middle column describes patterns commonly reported in audits of outsourced collections floors, not measurements of any specific client. The right-hand column describes how the control is implemented."
        />
      </Section>
      <Section
        eyebrow="Evidence"
        title={["One record", "answers the question."]}
        lede="An audit is a retrieval problem. It becomes an expensive one when the answer has to be assembled from a dialler, a CRM, a recording archive and somebody's memory."
      >
        <Rows
          items={[
            [
              "Policy version",
              "The rule set in force at that instant, not the one in force today. Rules are versioned data, so a decision made in March can be explained with March's rules.",
            ],
            [
              "Gate results",
              "Every check that ran, with its outcome — including the ones that were skipped and why, because a check that did not run must never read as a pass.",
            ],
            [
              "The decision behind it",
              "The action chosen, the alternatives it beat, and the expected value that justified it.",
            ],
            [
              "The conversation",
              "Recording and transcript, tied to the same record as the decision that caused the call and the number it came from.",
            ],
            [
              "Redaction",
              "Transcripts are masked as they are written and re-checked by models that recognise spoken numbers, names and one-time codes. Recordings get a copy with a tone over every spoken identity or card value, and only roles cleared for raw personal data can play the original, with every play logged.",
            ],
            [
              "Tamper evidence",
              "Each call's transcript and recording are hashed into a per-tenant chain. Verifying a record recomputes it, so an edited transcript shows up as edited.",
            ],
            [
              "Retention and legal hold",
              "Your schedule per record type, with deletion evidence — and a hold that suspends it, tamper-evident, for accounts under legal action.",
            ],
          ]}
        />
        <Pull by="What an inspection looks like afterwards">
          No call has ever been placed outside the window — enforced twice, logged both times.
        </Pull>
      </Section>
      <Section
        eyebrow="Outsourced floors"
        title={["Our vendor handled it", "is not a defence."]}
        lede={
          <>
            Under every conduct regime we have deployed under, the lender remains responsible for
            the conduct of the agencies acting on its behalf. That makes agency performance a
            visibility problem, and visibility is something a platform can actually provide.
          </>
        }
      >
        <Cols
          items={[
            [
              "Per-tenant policy",
              "Each agency floor runs its own policy set and its own agents, with the same gates applied and the same evidence produced.",
            ],
            [
              "Comparable scorecards",
              "One rubric across every floor, in-house and outsourced, so the comparison is like for like rather than an argument about methodology.",
            ],
            [
              "Consolidated audit",
              "One place to answer for the whole book, whoever placed the call, without a request going out to a partner and coming back a week later.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Questions" title={["What compliance teams", "ask first."]}>
        <Faq items={faqs["/compliance/"]} />
      </Section>
      <More
        links={[
          ["/security/", "Security and deployment", "Where the data sits, and what never leaves."],
          ["/agents/", "The agents", "Grants, gates and the authority envelope."],
          ["/product/", "Every module", "Audit trail, consent, redaction and scorecards."],
        ]}
      />
      <Closing
        title={["Bring your worst", "audit finding."]}
        lede="Tell us the question you could not answer quickly last year, and we will show you what the record would have looked like."
        secondary={{
          label: "See the platform",
          href: "/platform/",
        }}
      />
    </>
  );
}
