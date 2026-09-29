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
    "A bounce at 00:12 opens a case straight away, and the written notice is queued for the first permitted hour. Nothing waits for an allocation meeting.",
  ],
  [
    "Dialling",
    "Progressive dialler. Verify identity, disclose purpose, state the amount and the due date.",
    "Contact is planned to an hour the customer has historically answered, inside the permitted window, under the cap.",
  ],
  [
    "On the call",
    "Hang-ups, I-will-pay-Saturday, fee arguments, already-paid, waiver requests, a language switch.",
    "Identity comes first, then the promise. Anything outside policy goes to a person with the account packet already open.",
  ],
  [
    "After each call",
    "Notes, promise amount and date, callback, dispute flag, CRM update: the after-call work.",
    "The outcome is filed as a code, not a note, and the promise and its pay link are sent in writing during the call.",
  ],
  [
    "Afternoon",
    "Retry the no-answers, chase today's promises, take the inbound you-called-me.",
    "The promise carries a pay link and a reminder. When it breaks, the next action is decided that hour.",
  ],
  [
    "End of shift",
    "Assemble the report: attempts, contacts, promises, collected. Tomorrow's meeting asks why roll-forward moved.",
    "Recovered amount, promises kept, time to first touch and compliance flags are live on the dashboard, not assembled overnight.",
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
            under whose authority, then carries that decision out and keeps the evidence.
          </>
        }
        secondary={{
          label: "See every module",
          href: "/product/",
        }}
        proof={[
          "Bounces arrive as events",
          "Gates before scoring",
          "Voice, WhatsApp and people",
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
            and a structured intervention raises the chance of rolling into the next bucket, and
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
            Voice AI is becoming a commodity, and a product priced by the minute has to want more
            minutes. The defensible layer is the one that decides whether a contact is worth making
            at all. After that, adding a channel, a mandate re-presentation, a person or a field
            visit changes nothing upstream.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Decide",
                "Which accounts, which action, which channel, which hour, scored in money against doing nothing.",
              ],
              [
                "Gate",
                "Consent, calling window, contact caps across every channel, holds, identity and stale data.",
              ],
              [
                "Execute",
                "Voice, WhatsApp, a written notice, a person on the phone, a pay link, a mandate retry, or deliberate silence.",
              ],
              [
                "Evidence",
                "Rules in force, every rule consulted, score, recording, transcript. One record per action.",
              ],
              [
                "Learn",
                "Rates re-learned every night, a comparison group, and a promotion gate that says no until the evidence says yes.",
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
          rail
          items={[
            [
              "The event arrives, not the batch",
              "A mandate fails and the bounce reaches PayInt as a signed event, with its return reason. The case opens immediately. Account and payment data still arrive in your regular bank feeds, and if a feed is late, contact waits instead of guessing.",
            ],
            [
              "The engine picks an action",
              "Ten candidate actions, from waiting to a legal notice, are each planned to a specific moment, then vetoed, then scored in money. Waiting scores exactly zero, so anything that happens has to beat silence.",
            ],
            [
              "The gates decide whether it may happen",
              "Consent, calling hours, contact caps, third-party contact, holds and stale data are checked before anything is dialled, and the calling window is checked again at the dial. A vetoed action cannot be revived by a high score.",
            ],
            [
              "The agent has the conversation",
              "Identity first, then the amount and the due date, then the actual conversation. Anything outside policy, every settlement request included, goes to a person with the account packet already open.",
            ],
            [
              "The promise becomes an artefact",
              "Amount and date are captured on the call, confirmed in writing with a pay link while the customer is still on the line, and a reminder is set for the day it falls due.",
            ],
            [
              "The loop closes itself",
              "Kept or broken is worked out from the ledger, not from anyone's honour. A broken promise goes back to the engine the hour it breaks, with a cap of five attempts and a twelve-hour backoff, so the ladder stops instead of grinding.",
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
              note: "Tracked on the dashboard as a median, from the bounce to the first compliant touch. Days is the industry norm.",
            },
            {
              n: "Right party",
              k: "Contacts that reached the actual borrower",
              note: "Verified on every call before any account detail. Attempts per connect and right-party rate are measured, not guessed.",
            },
            {
              n: "100%",
              k: "Of conversations scored",
              note: "Voice Studio calls get the full grading, and every other conversation still gets a rules-based card, so the complained-about call is on record.",
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
          came from, who answered, what was said, what we promised, and whether we kept it. As one
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
              "Augmented. Floor command lets a lead listen to, whisper into or take over any live call, so supervision goes to the exceptions instead of the walk-around.",
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
              "The diary replaced by shared queues with owners and SLA timers: broken promises, callbacks, document requests and disputes.",
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
            "Why the engine decides and the model only explains.",
          ],
          [
            "/compliance/",
            "Compliance and QA",
            "Gates before contact, and every conversation scored.",
          ],
          ["/security/", "Security and deployment", "Your servers, your keys, your region."],
        ]}
      />
      <Closing
        title={["See a bounce become", "a conversation."]}
        lede="Thirty minutes, your book, your rules. We run one account end to end: the trigger, the gates, the decision, the conversation and the record it leaves behind."
      />
    </>
  );
}
