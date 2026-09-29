import React from "react";
import { Closing, Cols, Faq, More, PageHero, Pull, Rows, Section, Table } from "../components/ui";
import { faqs } from "../data/faqs";

const now = <span className="status status--now">Available now</span>;
const soon = <span className="status status--soon">In development</span>;

// Insurance is in early access: the lending engine's customer-wide machinery
// carries over today; policy and premium workflows are being built with partners.
const capabilityRows = [
  [
    "One contact budget per customer",
    now,
    "Daily caps and cooling-off span every channel for a customer, so two teams cannot each stay inside their own limit.",
  ],
  [
    "One hardship state",
    now,
    "A hardship hold placed on any conversation binds every agent and every channel for that customer.",
  ],
  [
    "Suitability before any offer",
    now,
    "Eligibility and suitability are checked before scoring, offers are never spoken on a call, and they go out later only with marketing consent.",
  ],
  [
    "One evidence trail",
    now,
    "Recording, transcript, rules and decisions land in the same audit store, whatever the conversation was about.",
  ],
  [
    "Policies and premiums in the record",
    soon,
    "Policy, premium and renewal data alongside the ledger in Customer 360.",
  ],
  [
    "Renewal reminders and premium mandates",
    soon,
    "Pre-due reminders with a payment link, and premium debits retried when the account is likely funded.",
  ],
  [
    "Grace periods and revival windows",
    soon,
    "A lapse ladder and a revival clock the engine can score against, measured on policies retained.",
  ],
];

export function InsurancePage() {
  return (
    <>
      <PageHero
        eyebrow="Insurers · Early access"
        title={["Persistency is collections", "with a thirteenth-", "month clock."]}
        lede={
          <>
            Most lapse is not a decision to leave. It is a failed auto-debit, an expired card or a
            renewal notice that arrived while somebody was travelling. The machinery PayInt runs on
            missed instalments fits that problem, and we are building the renewal and lapse
            workflows with a small group of design partners now.
          </>
        }
        primary={{ label: "Become a design partner", href: "/demo/" }}
        secondary={{ label: "See the platform", href: "/platform/" }}
        proof={[
          "Early access",
          "Built on the lending engine",
          "One contact budget per customer",
          "Suitability-gated offers",
        ]}
      />
      <Section
        eyebrow="The leak"
        title={["The steepest decay", "is the cheapest to fix."]}
        lede={
          <>
            Persistency falls hardest between the first and second renewal, and a large share of
            that fall is administrative rather than deliberate. It is pre-due work: remind, take the
            payment, confirm it. It rarely needs a specialist and it almost never needs a
            negotiation.
          </>
        }
      >
        <Cols
          items={[
            [
              "A missed debit is a timing problem",
              "Re-presenting a mandate at the right moment costs almost nothing, annoys nobody and sits outside the contact budget. For an insufficient-funds return it beats any call. This already works on loan mandates.",
            ],
            [
              "A forgotten renewal is a reminder problem",
              "A message with a payment link cures the same policy a call would, at a fraction of the cost, once you can tell that segment apart. That means capturing the reason, not guessing it.",
            ],
            [
              "A revival window is a deadline problem",
              "Lapsed policies stay revivable for years, and the value of contact fades across that window rather than falling off a cliff. A revival clock the engine can score against is part of what we are building.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Where it stands"
        title={["What works today,", "and what we are building."]}
        lede="We would rather you hear it from us than find it in a pilot. Here is the line between what runs now and what design partners are shaping with us."
        wide
      >
        <Table
          className="table--status"
          head={["Capability", "Status", "What it means"]}
          rows={capabilityRows}
        />
      </Section>
      <Section
        eyebrow="One customer"
        title={["Two queues is how", "you over-contact."]}
        lede={
          <>
            A customer behind on an instalment and lapsing a policy is one cash-flow story. Run as
            two systems, they get two contact budgets, two reminder cadences and two partial views,
            and the hardship signal one side captured is invisible to the other.
          </>
        }
      >
        <Rows
          items={[
            [
              "One contact budget",
              "The frequency cap is per customer, across every channel, so when policy servicing joins, a customer cannot be reached six times in a week by two teams each staying inside their own limit.",
            ],
            [
              "One hardship state",
              "A hold placed during a collections conversation binds every other agent too, at 02:00, without anyone forwarding an email.",
            ],
            [
              "One record",
              "The same customer view carries the ledger, the promises and every interaction, and is where policies will sit.",
            ],
            [
              "One evidence trail",
              "Whichever product the conversation was about, the recording, transcript, rules in force and gate results land in the same audit store.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Selling on the call"
        title={["Only what the customer", "is actually eligible for."]}
        lede={
          <>
            A renewal is a suitability-sensitive moment, and the temptation to attach a product to
            it is exactly why conduct rules exist around it.
          </>
        }
      >
        <Cols
          of={2}
          items={[
            [
              "Eligibility is a veto, not a ranking input",
              "The recommender cannot surface a product the customer does not qualify for. Eligibility is evaluated before anything is scored, so a high conversion score cannot promote an unsuitable product.",
            ],
            [
              "Nothing is sold on the call",
              "Offers are never spoken on a collections call. A buying signal becomes an offer only after an eligibility and suitability check, and goes out later by WhatsApp with marketing consent, or to a relationship manager as a lead.",
            ],
          ]}
        />
        <Pull by="The version of this a conduct team can sign">
          Nothing is offered on a call. Anything offered later has a written suitability finding
          behind it.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What insurers", "ask first."]}>
        <Faq items={faqs["/insurance/"]} />
      </Section>
      <More
        links={[
          ["/lenders/", "Banks and lenders", "The same pipeline on the lending book, today."],
          ["/decision-engine/", "Decision intelligence", "Why re-presenting often beats calling."],
          ["/compliance/", "Compliance and QA", "Suitability, disclosure and the evidence trail."],
        ]}
      />
      <Closing
        title={["Help us build", "the renewal side."]}
        lede="Bring one renewal cohort. We will map it onto the platform with you and measure the pilot on policies retained, against a comparison group."
        primary={{ label: "Become a design partner", href: "/demo/" }}
        secondary={{ label: "How we price it", href: "/pricing/" }}
      />
    </>
  );
}
