import React from "react";
import { Closing, Cols, Faq, More, PageHero, Pull, Rows, Section, Steps } from "../components/ui";
import { faqs } from "../data/faqs";

export function InsurancePage() {
  return (
    <>
      <PageHero
        eyebrow="Insurers"
        title={["Persistency is collections", "with a thirteenth-", "month clock."]}
        lede={
          <>
            Most lapse is not a decision to leave. It is a failed auto-debit, a card that expired, a
            renewal notice that arrived while somebody was travelling — the same chore as an
            early-stage instalment miss, with a longer cycle and a wider revival window. It responds
            to the same machinery.
          </>
        }
        secondary={{
          label: "The platform",
          href: "/platform/",
        }}
        proof={[
          "Renewals and pre-due",
          "Failed mandate recovery",
          "Revival windows",
          "Suitability-gated conversations",
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
              "Re-presenting the mandate at the right moment costs almost nothing, annoys nobody, and does not touch the contact budget. For an insufficient-funds return it is strictly better than any call.",
            ],
            [
              "A forgotten renewal is a reminder problem",
              "A message with a payment link cures the same policy a call would have cured, at a fraction of the cost — once you can tell that segment apart, which requires capturing the reason rather than guessing it.",
            ],
            [
              "A revival window is a deadline problem",
              "Lapsed policies stay revivable for years, and the value of contact decays across that window rather than falling off a cliff. That decay is in the score, so the engine works the window instead of the calendar month.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="The ladder" title={["From renewal notice", "to revived policy."]}>
        <Steps
          items={[
            [
              "Before it is due",
              "A reminder on the channel the policyholder actually uses, with a link that completes the payment. The cheapest cure available, and the one most programmes underuse.",
            ],
            [
              "The debit fails",
              "The event opens a case the same minute. If the return code says insufficient funds, the first response is a re-presentation timed to when the account is likely funded — not a call.",
            ],
            [
              "Inside the grace period",
              "Escalating, but still automated: message, then a voice agent that can take the payment, explain what lapse would cost, and capture a promise in writing.",
            ],
            [
              "After lapse",
              "The revival conversation, with the medical or underwriting requirements stated plainly and the deadline that matters made explicit rather than implied.",
            ],
            [
              "When it needs a person",
              "Hardship, a complaint, a dispute about what was sold, or a claim in progress. Those get a hold and a human, quickly, with the history already retrieved.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="One customer"
        title={["Two queues is how", "you over-contact."]}
        lede={
          <>
            A customer behind on an instalment and lapsing a policy is one cash-flow story. Run as
            two systems, they get two contact budgets, two reminder cadences and two partial views —
            and the hardship signal one side captured is invisible to the other.
          </>
        }
      >
        <Rows
          items={[
            [
              "One contact budget",
              "The frequency cap spans the lending and insurance books together, so a customer cannot be reached six times in a week by two teams each staying inside their own limit.",
            ],
            [
              "One hardship state",
              "A hold placed during a collections conversation binds the renewal agent too, at 02:00, without anyone forwarding an email.",
            ],
            [
              "One record",
              "The same customer view carries the ledger, the policies, the promises and every interaction on either side of the house.",
            ],
            [
              "One evidence trail",
              "Whichever product the conversation was about, the recording, transcript, policy version and gate results land in the same audit store.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Selling on the call"
        title={["Only what the customer", "is actually eligible for."]}
        lede={
          <>
            A renewal call is a suitability-sensitive moment, and the temptation to attach a product
            to it is exactly why conduct rules exist around it.
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
              "Collection and cross-sell stay separate",
              "An account in collections is not a cross-sell audience. The offer engine reads the same holds the treatment engine does, so that separation is enforced by policy rather than by remembering to.",
            ],
          ]}
        />
        <Pull by="The version of this a conduct team can sign">
          Nothing was offered on a renewal call that the customer could not have been sold in a
          branch.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What insurers", "ask first."]}>
        <Faq items={faqs["/insurance/"]} />
      </Section>
      <More
        links={[
          ["/lenders/", "Banks and lenders", "The same pipeline on the lending book."],
          ["/decision-engine/", "Decision intelligence", "Why re-presenting often beats calling."],
          ["/compliance/", "Compliance and QA", "Suitability, disclosure and the evidence trail."],
        ]}
      />
      <Closing
        title={["Start with one", "renewal month."]}
        lede="A pilot on a single cohort, with a held-out control group, measured on policies retained rather than on calls made."
        secondary={{
          label: "How we price it",
          href: "/pricing/",
        }}
      />
    </>
  );
}
