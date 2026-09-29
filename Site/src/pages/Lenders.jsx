import React from "react";
import { Closing, Cols, Faq, More, PageHero, Pull, Section, Steps, Table } from "../components/ui";
import { faqs } from "../data/faqs";

export function LendersPage() {
  return (
    <>
      <PageHero
        eyebrow="Banks, lenders and card issuers"
        title={["The first thirty days", "are a factory.", "Run it like one."]}
        lede={
          <>
            Early delinquency is high-volume, low-discretion and tightly regulated, and on most
            floors it is still a person with a headset, a list printed overnight and a daily target.
            It is the part of the book where speed and coverage decide the outcome, and both are
            things software is better at than staffing.
          </>
        }
        secondary={{
          label: "The decision engine",
          href: "/decision-engine/",
        }}
        proof={[
          "Cards, loans and unsecured",
          "In-house and agency floors",
          "Pre-due to late-stage triage",
          "Late data stops contact",
        ]}
      />
      <Section
        eyebrow="The operating model"
        title={["Automate the volume.", "Escalate the distress."]}
        lede={
          <>
            A book does not decay uniformly. A Day-1 miss is usually forgetfulness; a Day-90 account
            is distress and legal process. Putting the same treatment on both is how floors
            simultaneously over-contact the first and under-serve the second.
          </>
        }
        wide
      >
        <Table
          head={["Stage", "What the customer is", "The decision that has to be instant"]}
          rows={[
            [
              "Pre-due",
              "Not delinquent. Needs a reminder and a way to pay.",
              "Send the link now, capture intent, involve nobody. The cheapest cure in the whole book.",
            ],
            [
              "1–30 days",
              "Forgot, or a short cash-flow wobble. Still reachable and still willing.",
              "Contact the entire bucket inside 48 hours, capture a structured promise, confirm it in writing.",
            ],
            [
              "31–60 days",
              "Hesitation. Credit reporting starts to matter to them.",
              "Automated first touch, a person on the broken promise and on any complaint.",
            ],
            [
              "61–90 days",
              "Specialist territory. Field and legal are queued behind this.",
              "Triage only (willing, distressed or disputing), then route to the right person.",
            ],
            [
              "90+ days",
              "Distress, restructuring and statutory process.",
              "A person owns the recovery. Automation confirms logistics and keeps the clock.",
            ],
          ]}
          caption="The engine reflects this shape rather than being configured into it: as exposure and days past due rise, the expected value of a human conversation overtakes the expected value of another dial."
        />
      </Section>
      <Section eyebrow="Where the money is" title={["Three changes", "move the P&L."]}>
        <Steps
          items={[
            [
              "Work the failure the hour it happens",
              "A failed mandate opens a case the minute the bounce arrives, and the first compliant touch, a written notice with a pay link, goes out in the next permitted window. Re-presentation is proposed for when the account is likely to be funded, around the salary credit, with at least 48 hours between attempts, and a person confirms it before it goes to your loan system.",
            ],
            [
              "Cover the whole early book, not a sampled list",
              "Coverage is the lift in early delinquency; conversation quality matters more further down. A floor that can only dial a fraction of the bucket is choosing which accounts to let roll, usually by ticket size rather than by where the intervention would have mattered.",
            ],
            [
              "Make promises into artefacts",
              "Promises made is a vanity number. Amount and date captured on the call, confirmed in writing with a pay link before the call ends, a reminder on the day, and kept or broken worked out from the ledger rather than from anyone's honour.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Context"
        title={["What the published", "research supports."]}
        lede={
          <>
            Third-party figures, given with their sources so you can weigh them yourself. These are
            published ranges for digital-first and generative-AI collections programmes generally.
            They are not measurements of a PayInt deployment, and we do not present them as ours.
          </>
        }
      >
        <Cols
          items={[
            [
              "Cost to collect",
              "McKinsey reports up to a 40% reduction in operating cost for generative-AI-enabled credit customer assistance, and a 15% cost-to-collect reduction in a retail banking case study.",
            ],
            [
              "Recovery",
              "The same body of work reports roughly a 10% recovery uplift, with more customers cured through self-service channels and digital payment volumes doubling in the case study cited.",
            ],
            [
              "Experience",
              "Customer-satisfaction improvements of up to 30% are reported alongside those cost and recovery figures, an outcome that is unusual in collections, where cost reduction normally comes at the customer's expense.",
            ],
          ]}
        />
        <p className="note rise" data-fx>
          {"Sources: McKinsey & Company, "}
          <em>The promise of generative AI for credit customer assistance</em>
          {" (2024) and "}
          <em>Holistic customer assistance</em>. We will walk through the methodology behind our own
          figures, and their limits, in the walkthrough.
        </p>
      </Section>
      <Section
        eyebrow="What stays human"
        title={["Judgement is not", "a volume problem."]}
        lede="The point of automating the early book is that hardship, disputes, settlements and complaints stop competing for the same hour."
      >
        <Cols
          of={4}
          items={[
            ["Hardship", "Job loss, illness, bereavement. A hold, then a person, quickly."],
            [
              "Disputes",
              "Already-paid claims and fee arguments, as a queue with evidence attached.",
            ],
            ["Settlements", "Always a person. Voice agents have no settlement or waiver tool, by design."],
            ["Complaints", "Routed with the recording and the decision record already retrieved."],
          ]}
        />
        <Pull by="The result a collections head wants to take upstairs">
          Fewer contacts, the same recovery, and an answer for every call we made.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What lenders", "ask first."]}>
        <Faq items={faqs["/lenders/"]} />
      </Section>
      <More
        links={[
          ["/insurance/", "Insurance", "The same factory, with a renewal clock."],
          ["/decision-engine/", "Decision intelligence", "Why fewer calls can recover more."],
          ["/compliance/", "Compliance and QA", "What an audit looks like afterwards."],
        ]}
      />
      <Closing
        title={["Start with one", "bucket, one month."]}
        lede="A pilot on a defined slice of the early book, with a comparison group, and an audit pack when it ends."
      />
    </>
  );
}
