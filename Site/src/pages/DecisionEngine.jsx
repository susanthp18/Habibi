import React from "react";
import { Helix } from "../components/Helix";
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

const actionRows = [
  ["Wait", "No contact", "Scores exactly zero. Every other action has to beat it."],
  [
    "Re-present the mandate",
    "No channel",
    "Costs almost nothing, annoys nobody, invisible to the contact cap. For an insufficient-funds return it is a timing problem, and this is strictly better than any call.",
  ],
  [
    "Message with a pay link",
    "Messaging",
    "Cures the forgot segment at a fraction of a call. Timed to the credit, not the calendar.",
  ],
  [
    "Voice agent",
    "Voice",
    "Volume work in the early book: identity, disclosure, amount, promise, objection.",
  ],
  [
    "Human call",
    "Voice",
    "Hardship, disputes, settlement, and anything the authority envelope will not cover.",
  ],
  [
    "Field visit",
    "In person",
    "Expensive and often unanswered. Earned only when digital is exhausted and exposure warrants it.",
  ],
  ["Statutory notice", "Legal", "A clock, not a conversation. Permitted even under a legal hold."],
];
export function DecisionEnginePage() {
  return (
    <>
      <PageHero
        eyebrow="Decision intelligence"
        title={["Don't predict who repays.", "Predict who repays", "because you acted."]}
        lede={
          <>
            Most collections models rank customers by how likely they are to pay. That puts the
            people who were going to pay anyway at the top of the list, spends your most expensive
            capacity on them, and books their payment as the model's own success. PayInt scores the
            difference your action makes instead.
          </>
        }
        secondary={{
          label: "See the platform",
          href: "/platform/",
        }}
        proof={[
          "Uplift, not propensity",
          "Vetoes before scoring",
          "Scored in money",
          "Control arm, always",
        ]}
      />
      <Section
        eyebrow="The thesis"
        title={["One equation, and", "everything follows from it."]}
        lede={
          <>
            The quantity worth estimating is not the probability that a customer cures. It is the
            increase in that probability caused by the action you are considering.
          </>
        }
      >
        <div className="formula rise" data-fx>
          <p className="formula__eq">
            <span>τ(action, x)</span>
            {" = P(cure | action) − P(cure | no action)"}
          </p>
          <p className="formula__note">
            Read it as: what this intervention is worth on this account, over and above leaving it
            alone. A response model estimates the first term and ignores the second, which is why it
            recommends contacting self-curers.
          </p>
        </div>
        <Cols
          items={[
            [
              "The self-cure trap",
              "A large share of early delinquency resolves without you. A propensity ranking finds those accounts first, contacts them, and reports a magnificent recovery rate that would have happened anyway.",
            ],
            [
              "The sleeping-dog trap",
              "For some accounts, contact makes things worse — a complaint, an opt-out, an escalation. Uplift can go negative, and an engine that cannot represent a negative cannot avoid it.",
            ],
            [
              "The persuadable middle",
              "The accounts worth your capacity are the ones where the action changes the outcome. They are neither the most likely nor the least likely to pay, which is exactly why propensity misses them.",
            ],
          ]}
        />
      </Section>
      <section className="helixband">
        <div className="shell helixband__in">
          <div className="helixband__copy">
            <p className="eyebrow rise" data-fx>
              The gap
            </p>
            <h2 className="display" data-split>
              <span className="line">
                <i>Two curves. The gap</i>
              </span>
              <span className="line">
                <i>is the whole product.</i>
              </span>
            </h2>
            <p className="rise" data-fx>
              One strand is what happens to an account if you act. The other is what happens if you
              leave it alone. A propensity model measures the first and never looks at the second —
              and across most of a book the two are the same line, which is exactly where the money
              is being spent for nothing.
            </p>
          </div>
          <Helix />
        </div>
      </section>
      <Panel
        eyebrow="The pipeline"
        title={["The ordering is", "the architecture."]}
        lede={
          <>
            Candidate actions are planned, then vetoed, then scored, then arbitrated, then logged.
            Vetoing before scoring is what makes compliance structural rather than aspirational: a
            high score cannot resurrect an action that a gate refused, because scoring never sees
            it.
          </>
        }
      >
        <div className="os">
          <div className="os__stack">
            {[
              [
                "Features",
                "Point-in-time correct. A feature computed from data that did not exist yet is how a model learns to cheat.",
              ],
              [
                "Candidates",
                "The full action ladder, each one planned to a specific instant — because asking may-we-dial at 02:00 answers no for every customer alive.",
              ],
              [
                "Veto",
                "Consent, calling window, cross-channel frequency, cooling-off, third-party contact, hardship, dispute, bereavement and legal holds.",
              ],
              ["Score", "Expected value in money for each surviving candidate."],
              ["Arbitrate", "One action wins, with the reasons that eliminated the others."],
              [
                "Log",
                "Every invocation, including the suppressed ones, with the propensity it was chosen under.",
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
        eyebrow="The score"
        title={["Money, not a", "confidence number."]}
        lede={
          <>
            A collections head can argue with a figure in currency, and can do nothing at all with a
            0.62. Every candidate carries an expected value built from terms that each mean
            something on their own.
          </>
        }
      >
        <div className="formula rise" data-fx>
          <p className="formula__eq formula__eq--small">
            exposure × recovery fraction × P(reach) × P(resolve | reach) × decay(delay) − cost −
            contact fatigue
          </p>
          <p className="formula__note">
            Waiting evaluates to exactly zero, so a recommended action is always an assertion that
            doing something beats doing nothing on this account, today, by this much.
          </p>
        </div>
        <Rows
          items={[
            [
              "Timing is scored, not asked afterwards",
              "Each candidate is planned to an instant before it is vetoed. Digital nudges land near the credit when the failure was insufficient funds; calls prefer an hour this customer has actually answered at; a field visit takes a day's notice and skips the weekend.",
            ],
            [
              "Cost is real, not nominal",
              "Attempts per connect dominates the cost base and is usually unmeasured. At a 30% answer rate a connect costs 3.3 rings; at 15% it costs 6.7. That is a two-fold swing in the economics of the whole operation, so the platform measures it rather than assuming it.",
            ],
            [
              "Fatigue is a term, not a policy afterthought",
              "Contact has a cost to the relationship as well as to the P&L. It is priced in the score, on top of the hard frequency cap that no score can override.",
            ],
            [
              "Book-level allocation, not just per-account",
              "Agent hours and field slots are finite. Ranking accounts independently overspends the scarcest resource first; the allocation layer prices that scarcity and spends it where uplift is highest.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="The action space"
        title={["Seven things to do,", "and one of them is nothing."]}
        lede="Silence is a first-class action with a real score, which is the only way an engine can ever recommend fewer contacts."
        wide
      >
        <Table
          head={["Action", "Channel", "When it wins"]}
          rows={actionRows.map(([f, a, r]) => [f, a, r])}
          caption="Field visits and statutory notices are recommended and logged before any dispatcher exists — so a collections head can see how much field work the ladder would generate before anyone builds it."
        />
      </Section>
      <Section
        eyebrow="The model's job"
        title={["The model speaks.", "The engine decides."]}
        lede={
          <>
            There is a real and useful role for a language model in a collections conversation.
            Choosing what happens to somebody's money is not it.
          </>
        }
      >
        <div className="split">
          <div className="split__col rise" data-fx>
            <h3 className="split__h">What the model does</h3>
            <ul className="ticks ticks--yes">
              <li>
                Understands what the customer said, and follows if they switch language mid-call
              </li>
              <li>Captures the reason a payment failed as a structured field</li>
              <li>Negotiates inside an envelope the authority matrix has already drawn</li>
              <li>Reorders a shortlist that has already been approved</li>
              <li>Drafts one line of rationale for the record</li>
            </ul>
          </div>
          <div className="split__col rise" data-fx>
            <h3 className="split__h">What it cannot do</h3>
            <ul className="ticks ticks--no">
              <li>Introduce an action that was not on the approved shortlist</li>
              <li>Resurrect anything a gate vetoed</li>
              <li>Change the channel or the instant an action was planned for</li>
              <li>Quote a settlement percentage or approve a waiver</li>
              <li>State a figure that was not in the payload it was handed</li>
            </ul>
          </div>
        </div>
        <p className="note rise" data-fx>
          The last one is enforced in code: a rationale containing a number the engine did not
          supply is rejected outright rather than corrected. Customer speech reaches that context
          through the account summary, so the constraint cannot be talked around from inside the
          conversation.
        </p>
      </Section>
      <Section
        eyebrow="Stopping"
        title={["Five reasons to stop", "get a row, not a label."]}
        lede={
          <>
            Hardship, dispute, complaint, bereavement and legal each place a hold on the account. A
            hold is a record the runtime reads, which is what binds an agent at 02:00 exactly as it
            binds a supervisor at noon.
          </>
        }
      >
        <Cols
          of={2}
          items={[
            [
              "A hold is not a routing label",
              "Routing labels are advisory and get lost between systems. A hold is checked at the point of action, so nothing downstream has to remember it.",
            ],
            [
              "Holds are precise about what they stop",
              "A legal hold still permits a statutory notice. A dispute hold still permits a specialist call about the dispute itself. Blanket silence is its own failure mode.",
            ],
            [
              "Cross-sell is separated by policy",
              "The offer engine reads the same holds, so an account in collections cannot be pitched a product on the same breath — a separation regulators expect and agent training does not reliably deliver.",
            ],
            [
              "The ladder stops on its own",
              "A broken promise re-enters the engine the hour it breaks, with an attempt cap, a backoff and a repeat penalty. Following up forever is a bug, not persistence.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Proving it"
        title={["A number nobody", "can argue with."]}
        lede="An engine that cannot be evaluated is a story. The measurement apparatus ships with it."
      >
        <Steps
          items={[
            [
              "Shadow first, always",
              "The engine runs and logs every decision, including the suppressed ones, without acting. A fortnight of that tells you what it would have done and what it would have cost, before anything changes for a customer.",
            ],
            [
              "Exploration with logged propensities",
              "Actions are sometimes chosen with deliberate randomisation, and the probability of that choice is recorded. Without it, no honest off-policy estimate is possible later.",
            ],
            [
              "A genuine control arm",
              "A randomised group stays on the existing process. This is the only thing that separates lift from seasonality, and it is why the platform will not report uplift without one.",
            ],
            [
              "Off-policy evaluation before promotion",
              "A challenger policy is estimated against logged data — importance sampling, self-normalised, and doubly robust — so it can be compared before it ever touches a customer.",
            ],
            [
              "A promotion gate that refuses by default",
              "Drift and calibration monitors run continuously, and a challenger is promoted only when it clears the gate. Silence from the gate means no, not yes.",
            ],
          ]}
        />
        <Pull by="What this buys, said plainly">
          We reduced contact attempts by a third and recovered the same amount — measured against a
          control arm, not asserted.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What people ask", "about the engine."]}>
        <Faq items={faqs["/decision-engine/"]} />
      </Section>
      <More
        links={[
          ["/agents/", "The agents", "What executes the decision, and what it may not do."],
          ["/pricing/", "Pricing", "Why fewer calls has to be good for both of us."],
          ["/compliance/", "Compliance", "The vetoes, and the evidence they leave."],
        ]}
      />
      <Closing
        title={["Bring your book.", "We will score it."]}
        lede="In a walkthrough we run the engine over real accounts of yours in shadow mode and show you what it would have done, what it would have suppressed, and why."
        secondary={{
          label: "Read the architecture",
          href: "/security/",
        }}
      />
    </>
  );
}
