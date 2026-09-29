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
  Table,
} from "../components/ui";
import { faqs } from "../data/faqs";
import { moduleCount } from "../data/modules";

export function PricingPage() {
  return (
    <>
      <PageHero
        eyebrow="Pricing"
        title={["Priced on resolutions,", "not on minutes."]}
        lede={
          <>
            The first observable effect of a working decision engine is that call volume falls. It
            discovers that a large share of early-bucket dialling is worth less than silence, and it
            stops. Priced per minute, we would be selling you a system whose best behaviour costs us
            money, so we do not price it that way.
          </>
        }
        secondary={{
          label: "Why fewer calls recovers more",
          href: "/decision-engine/",
        }}
        proof={[
          "No per-seat licence",
          "No per-minute billing",
          "Fixed-fee pilot",
          "Measured against a comparison group",
        ]}
      />
      <Panel
        eyebrow="The principle"
        title={["The incentive must", "survive the design."]}
        lede={
          <>
            This is not a positioning preference. It follows from how the product works, and it is
            far easier to choose now than to renegotiate after a contract has been shaped the other
            way.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Priced per minute",
                "The intelligence layer cannibalises the revenue line. Every suppressed call is lost income, and the vendor's interest is in more conversation rather than less delinquency.",
              ],
              [
                "Priced per seat",
                "The unit is headcount, on a floor whose headcount should be falling on the early book. You would be paying for the problem rather than the outcome.",
              ],
              [
                "Priced per resolution",
                "Fewer contacts and the same recovery is the pitch rather than the risk. Our incentive and yours point the same way, which is the only durable arrangement.",
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
        eyebrow="Engagements"
        title={["Three shapes.", "One product underneath."]}
        lede="Every deployment runs the same platform. What changes is the scope of the book, who hosts it, and how the commercial terms are struck."
        wide
      >
        <Table
          head={["", "Pilot", "Production", "Agency network"]}
          rows={[
            [
              "Scope",
              "One bucket or one cohort, thirty days.",
              "The whole early book, with late-stage triage.",
              "Your own floor plus agency partners under one statutory rule set.",
            ],
            [
              "Priced on",
              "A fixed fee, agreed before it starts.",
              "Resolved contacts, with a platform fee for the deployment.",
              "Resolved contacts, with a tenant per floor.",
            ],
            [
              "Deployment",
              "Your infrastructure, standard topology.",
              "Your servers or your cloud account, with self-hosted models where required.",
              "Your servers or cloud account, a tenant per floor.",
            ],
            [
              "Includes",
              "A comparison group and an audit pack on exit.",
              "All modules, unlimited users, your own agents and policy.",
              "Everything in production, plus agency dialler records checked against the same caps.",
            ],
            ["Never priced on", "Minutes or seats.", "Minutes or seats.", "Minutes or seats."],
          ]}
          caption="Rates depend on book size, channel mix and deployment model, so they are quoted rather than listed. We will put a number in front of you on the second call, not the sixth."
        />
      </Section>
      <Section
        eyebrow="The model"
        title={["The arithmetic,", "with its own caveats."]}
        lede={
          <>
            Here is the cost model we use, stated as a model rather than as a claim. Every input is
            something to be measured in your environment. We will not quote a figure that has your
            book's name on it before we have seen your book.
          </>
        }
      >
        <div className="formula rise" data-fx>
          <p className="formula__eq formula__eq--small">
            cost per connect = (attempts per connect × cost per attempt) + (talk minutes ×
            per-minute cost) + platform
          </p>
          <p className="formula__eq formula__eq--small">
            value per connect = P(objective met | connect) × τ(action) × exposure × recovery
            fraction
          </p>
          <p className="formula__note">
            Two properties matter more than any number placed in them. Attempts per connect
            dominates the cost base and is usually unmeasured: at a 30% answer rate a connect costs
            3.3 rings, at 15% it costs 6.7, which is a two-fold swing in the economics of the whole
            operation. And τ is incremental: a system that books self-curers as its own success
            shows a magnificent recovery rate and adds nothing.
          </p>
        </div>
        <Cols
          items={[
            [
              "What we measure first",
              "Attempts per connect, right-party contact rate and the reason a payment failed. Those three reprice more of a collections operation than any model change.",
            ],
            [
              "What we will not do",
              "Quote a recovery uplift for your book before the pilot. The published ranges for this category are real, and they are also not a promise about you.",
            ],
            [
              "What you get either way",
              "The measurement apparatus. Logged decisions, a comparison group and an audit pack are part of the product, not a consulting add-on.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="What is included" title={["No modules held back", "for a bigger tier."]}>
        <Rows
          items={[
            [
              "Every module",
              `All ${moduleCount}. Feature-gating a compliance module behind a price tier is not a business model we are willing to operate.`,
            ],
            [
              "Unlimited users",
              "Supervisors, QA analysts, compliance and audit read-only users cost nothing to add. Charging for the people who check the work is perverse.",
            ],
            [
              "Your own agents and policy",
              "Authored by you, versioned, reviewable. No professional-services dependency to change a script or a rule.",
            ],
            [
              "The evidence",
              "Recordings, transcripts, decision records and exports are yours, in your deployment, and remain readable if you leave.",
            ],
          ]}
        />
        <Pull by="The commitment behind the pricing model">
          If the engine tells us to make fewer calls, that has to be good news for both of us.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What procurement", "asks first."]}>
        <Faq items={faqs["/pricing/"]} />
      </Section>
      <More
        links={[
          [
            "/decision-engine/",
            "Decision intelligence",
            "Why suppression is the valuable behaviour.",
          ],
          ["/security/", "Deployment", "What running it on your estate involves."],
          ["/platform/", "The platform", "What you are actually buying."],
        ]}
      />
      <Closing
        title={["Ask for the number", "on the second call."]}
        lede="Tell us the book size, the channel mix and the deployment model, and we will price a pilot before you have sat through a demo."
      />
    </>
  );
}
