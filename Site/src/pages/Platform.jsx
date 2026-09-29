import React from "react";
import {
  Closing,
  Faq,
  Metrics,
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
import { moduleCount, moduleGroups } from "../data/modules";

const shiftRows = [
  [
    "Before the shift",
    "Log in, take last night's allocated list, skim the broken promises and callbacks.",
    "The bounce at 00:12 opens a case at 00:13. Nothing waits for an allocation meeting.",
  ],
  [
    "Dialling",
    "Progressive dialler. Verify identity, disclose purpose, state the amount and the due date.",
    "Contact is planned to an hour the customer has historically answered, inside the permitted window, under the cap.",
  ],
  [
    "On the call",
    "Hang-ups, I-will-pay-Saturday, fee arguments, already-paid, waiver requests, a language switch.",
    "Goodwill inside policy closes on the call. Anything outside it warm-transfers with the packet already open.",
  ],
  [
    "After each call",
    "Notes, promise amount and date, callback, dispute flag, CRM update — the after-call work.",
    "Disposition is structured from the turn itself, and the promise is confirmed in writing within minutes.",
  ],
  [
    "Afternoon",
    "Retry the no-answers, chase today's promises, take the inbound you-called-me.",
    "The promise carries a pay link and a reminder. When it breaks, the next action is decided that hour.",
  ],
  [
    "End of shift",
    "Assemble the report: attempts, contacts, promises, collected. Tomorrow's meeting asks why roll-forward moved.",
    "Collection efficiency, roll-forward, promises kept and compliance flags are live, not assembled overnight.",
  ],
];
export function PlatformPage() {
  return (
    <>
      <PageHero
        eyebrow="The platform"
        title={["One pipeline from bounce", "to paid instalment."]}
        lede={
          <>
            PayInt is not a voice agent with a dashboard around it. It is the operating system for a
            collections floor: it decides which accounts to work, on which channel, at what hour and
            under whose authority — then executes that decision and keeps the evidence.
          </>
        }
        secondary={{
          label: "See every module",
          href: "/product/",
        }}
        proof={[
          "Event-driven, not batch",
          "Gates before scoring",
          "Voice, messaging, human",
          "Evidence on every action",
        ]}
      />
      <Section
        eyebrow="The problem"
        title={["The profit lever is", "delay, not dialogue."]}
        lede={
          <>
            A customer who misses an instalment on Day 1 and hears from you on Day 12 has already
            reclassified the debt in their own mind, and in your book. Every hour between the event
            and a structured intervention raises the chance of rolling into the next bucket — and
            almost none of those hours are spent talking.
          </>
        }
      >
        <Table
          head={["The shift", "What the hours go on today", "What happens instead"]}
          rows={shiftRows.map(([f, a, r]) => [f, a, r])}
          caption="The chore column is the job as it is actually run on a collections floor. Killing after-call work is what lets the next attempt happen now rather than tomorrow."
        />
      </Section>
      <Panel
        eyebrow="Positioning"
        title={["Voice is a channel.", "The decision is the product."]}
        lede={
          <>
            Voice AI is commoditising, and a product priced by the minute has to want more minutes.
            The defensible layer is the one that decides whether a contact is worth making at all —
            after which adding email, push, a mandate re-presentation, a human agent or a field
            visit changes nothing upstream.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Decide",
                "Which accounts, which action, which channel, which hour — scored in money against doing nothing.",
              ],
              [
                "Gate",
                "Consent, calling window, frequency across every channel, authority, hardship and legal holds.",
              ],
              [
                "Execute",
                "Voice, messaging, the agent desktop, a document, a pay link, or deliberate silence.",
              ],
              [
                "Evidence",
                "Policy version, gate results, score, recording, transcript — one record per action.",
              ],
              [
                "Learn",
                "Logged propensities, a held-out control arm, and a promotion gate that refuses by default.",
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
        eyebrow="The loop"
        title={["From a failed mandate", "to a written promise."]}
        lede="One account, one morning, with nothing waiting for a person to notice it."
      >
        <Steps
          items={[
            [
              "The event arrives, not the batch",
              "A mandate fails and the payment event reaches the runtime the same minute it hits the core system. The case opens immediately; there is no overnight extract and no morning allocation.",
            ],
            [
              "The engine picks an action",
              "Candidate actions — wait, message, voice, human, field, notice — are each planned to an instant, then vetoed, then scored in money. Waiting scores exactly zero, so anything that happens has to beat silence.",
            ],
            [
              "The gates decide whether it may happen",
              "Consent, permitted hours, cross-channel frequency, third-party contact, hardship and legal holds are evaluated before the contact exists. A vetoed action cannot be revived by a high score.",
            ],
            [
              "The agent has the conversation",
              "Identity, disclosure, the amount and the due date, then the actual negotiation — within an authority envelope that is on screen before it is spoken.",
            ],
            [
              "The promise becomes an artefact",
              "Amount, date and channel are captured from the turn, confirmed in writing within minutes, given a pay link, and scheduled for a reminder on the day.",
            ],
            [
              "The loop closes itself",
              "Kept or broken is computed from the ledger rather than from anyone's honour. A broken promise re-enters the engine the hour it breaks, with an attempt cap and a backoff so the ladder stops instead of grinding.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="The scoreboard"
        title={["The numbers a collections", "head is actually judged on."]}
        lede="Not conversation quality. Coverage, speed, and whether the promise turned into money."
      >
        <Metrics
          items={[
            {
              n: "Hours",
              k: "Time to first touch after a failed payment",
              note: "The early-bucket profit lever. Days is the industry norm; the target is inside the next permitted window.",
            },
            {
              n: "48h",
              k: "To cover the whole early book",
              note: "Coverage is the lift in early delinquency. Dialogue quality matters most further down the book.",
            },
            {
              n: "100%",
              k: "Of conversations scored",
              note: "There is no sampling path in the runtime, so the complained-about call is always in the record.",
            },
            {
              n: "Kept",
              k: "Promises, not promises made",
              note: "Capture without a keep rate is vanity. Keep and break are computed from the ledger.",
            },
          ]}
        />
        <Pull by="What a bank asks for, in a bank's language">
          Every recovery call we made in March, with the rule set that authorised it, the number it
          came from, who answered, what was said, what we promised, and whether we kept it — as one
          query.
        </Pull>
      </Section>
      <Section
        eyebrow="Who does what now"
        title={["Replace the volume.", "Keep the judgement."]}
        lede={
          <>
            Automation belongs where the work is high-volume and low-discretion. Hardship, disputes,
            settlements and complaints are not those, and the platform is built to route them to a
            person quickly rather than to argue with them cheaply.
          </>
        }
      >
        <Rows
          items={[
            [
              "Tele-collections",
              "Replaced at volume in pre-due and early delinquency. Coverage stops being a sampled list and becomes the whole book.",
            ],
            [
              "Floor lead",
              "Augmented. Floor command and call flags replace the walk-around and the spreadsheet pack, so supervision goes to the exceptions.",
            ],
            [
              "QA analyst",
              "Sampling replaced with complete scoring. Analysts calibrate the rubric and coach the flags instead of listening to a fraction of the day.",
            ],
            [
              "Consent and do-not-contact desk",
              "The spreadsheet replaced by hard gates. Frequency is capped across voice and messaging together, so persistent contact is not reachable.",
            ],
            [
              "Back-office clerk",
              "The diary replaced by queues that act: broken promises, callbacks, documents and dispute evidence.",
            ],
            [
              "Hardship, legal and field specialists",
              "Not replaced. Fed the same hour, with the transcript, the promise history and the clock that matters.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="The product"
        title={[`${moduleCount} modules.`, "One governed pipeline."]}
        lede={
          <>
            Every layer writes to the same customer record and the same evidence log, which is the
            difference between a platform and a folder of tools.{" "}
            <a href="/product/">See what each module does</a>.
          </>
        }
      >
        <div className="cols cols--4">
          {moduleGroups.map((f) => (
            <div className="rise" data-fx key={f.name}>
              <h3>{f.name}</h3>
              <p>{f.note}</p>
              <ul className="ticks">
                {f.items.map(([a]) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>
      <Section eyebrow="Questions" title={["Before you book", "half an hour."]}>
        <Faq items={faqs["/platform/"]} />
      </Section>
      <More
        links={[
          [
            "/decision-engine/",
            "Decision intelligence",
            "Why the engine decides and the model only speaks.",
          ],
          [
            "/compliance/",
            "Compliance and QA",
            "Gates before contact, and every conversation scored.",
          ],
          ["/security/", "Security and deployment", "The whole runtime inside your perimeter."],
        ]}
      />
      <Closing
        title={["See a bounce become", "a conversation."]}
        lede="Thirty minutes, your book, your rules. We run one live account end to end — the trigger, the gates, the decision, the call, and the record it leaves behind."
        secondary={{
          label: "How we price it",
          href: "/pricing/",
        }}
      />
    </>
  );
}
