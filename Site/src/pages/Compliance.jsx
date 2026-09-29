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
            gets complained about. PayInt gives every conversation a scorecard, refuses contact that
            would break a rule before anything is dialled, and keeps one record per action that
            answers the question an auditor actually asks.
          </>
        }
        secondary={{
          label: "Deployment and security",
          href: "/security/",
        }}
        proof={[
          "Every conversation scored",
          "Gates before the dial",
          "Recordings beeped over personal data",
          "Hash-chained evidence",
        ]}
      />
      <Section
        eyebrow="The gap"
        title={["The call that matters", "is not in the sample."]}
        lede={
          <>
            Quality assurance by sampling has a selection problem, not a volume problem. On a large
            floor, tens of thousands of conversations a day are never heard by anyone, and the one
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
              k: "Of conversations get a scorecard",
              note: "Voice Studio calls get the full grading. Every other conversation still gets a rules-based card, so nothing goes unreviewed.",
            },
            {
              n: "4",
              k: "Local models on every call, with no internet access",
              note: "Personal-data detection, intent, sentiment and beep timing run inside your deployment. The AI judge only ever sees a masked transcript.",
            },
            {
              n: "2",
              k: "Calling-window checks on every dial",
              note: "When the action is planned and again when it is placed, in the customer's time zone. If the check cannot run, the call does not happen.",
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
                "Worked out in the customer's time zone, 08:00 to 19:00 by default, and checked twice: when the action is planned and again at the dial, including calls the voice engine starts itself.",
              ],
              [
                "Do-not-contact",
                "A do-not-disturb flag blocks every channel. An opt-out on a call takes effect immediately, for that channel or for every channel if the customer asks.",
              ],
              [
                "Frequency",
                "One daily cap and one cooling-off period across voice and messaging together, with a weekly limit on top. Capping per channel is how a floor makes persistent contact by accident.",
              ],
              [
                "Consent",
                "Recorded per channel and per purpose, servicing or promotional, with where it came from. A marketing message without a promotional opt-in is refused.",
              ],
              [
                "Third-party contact",
                "Refused, always. There is no path to dial a relative or a reference, and the voice engine refuses any number that is not the customer or one of your test handsets.",
              ],
              [
                "Authority",
                "Settlements always go to a person, and voice agents have no waiver tool at all. Out-of-policy requests transfer with the account packet on screen.",
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
              "Refused at planning and again at the dial, and the refusal is recorded",
            ],
            [
              "Missing or partial disclosure",
              "Varies by agent, by script version and by how the day is going",
              "Written into the agent's greeting, checked at publish, and flagged on any call that skips it",
            ],
            [
              "Frequency and persistent contact",
              "Capped per channel, if at all, so the combined total is nobody's number",
              "One daily cap across channels, checked before every attempt",
            ],
            [
              "Unauthorised third-party contact",
              "Hard to detect after the fact, easy to do under pressure",
              "No path to dial anyone but the customer",
            ],
            [
              "Recording coverage",
              "Partial, with gaps that surface exactly when they matter",
              "Every Voice Studio call recorded, with the transcript in the same record",
            ],
            [
              "Pressure, intimidation, false statements",
              "Caught only if the call was in the sample",
              "Scored on every Voice Studio call, with the turn that proves it attached to the score",
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
              "The rule set in force at that moment, not the one in force today. Every rule consulted is recorded with its version and whether it fired.",
            ],
            [
              "What was blocked, and why",
              "Every option the engine considered, including the ones blocked before scoring, with the reason in plain language.",
            ],
            [
              "The decision behind it",
              "The action chosen, the alternatives it beat, and the expected value that justified it.",
            ],
            [
              "The conversation",
              "Recording and transcript, tied to the same record as the decision that caused the call.",
            ],
            [
              "Redaction",
              "Transcripts are masked as they are written: spoken digits in English, Hindi, Tamil and Arabic, card and Aadhaar numbers, one-time codes and PINs, names found by a local model, and anything matching the customer's own record. Recordings get a copy with a tone over every finding. Only roles cleared for raw personal data can play the original, every play is logged, and the play is refused if the log cannot be written.",
            ],
            [
              "Tamper evidence",
              "Each Voice Studio call's original transcript and recording are hashed into a per-tenant chain, alongside consent changes, opt-outs, ledger postings and agent publishes. Verify now recomputes it, so an edited original shows up as edited.",
            ],
            [
              "Exports and complaint packs",
              "Watermarked PDF exports, including Hindi, Tamil and Arabic, redacted audio with a hash manifest, and a complaint pack per customer that will not build if any section is missing.",
            ],
            [
              "Retention",
              "Rules per record type, each with its legal citation, changed only with a second person's approval. Expired call records are redacted in place.",
            ],
          ]}
        />
        <Pull by="What an inspection looks like afterwards">
          Every dial checked against the window twice, and every refusal on the record.
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
              "Stricter, never looser",
              "The statutory rule set is published with two-person approval, and a tenant can only make it stricter.",
            ],
            [
              "Agency records, same caps",
              "Call records from an agency's own dialler can be loaded and checked against the same caps and calling window, so a breach shows up whoever dialled.",
            ],
            [
              "Floors on PayInt",
              "Agency floors that run on PayInt use the same agents, gates, rubric and evidence trail as your own.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Questions" title={["What compliance teams", "ask first."]}>
        <Faq items={faqs["/compliance/"]} />
      </Section>
      <More
        links={[
          [
            "/security/",
            "Security and deployment",
            "Where the data sits, and whose keys it runs on.",
          ],
          ["/agents/", "The agents", "Pinned tools, the release gate and live supervision."],
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
