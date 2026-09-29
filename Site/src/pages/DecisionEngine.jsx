import React from "react";
import { Helix } from "../components/Helix";
import { Trace } from "../components/Trace";
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

// The ten candidate actions, as backend/agent_core/treatment/actions.py defines them.
const actionRows = [
  ["Wait", "No contact", "Scores exactly zero. Every other action has to beat it."],
  [
    "Re-present the mandate",
    "No contact",
    "Costs almost nothing, annoys nobody and sits outside the contact cap. For an insufficient-funds return it is a timing problem, and this beats any call.",
  ],
  [
    "Change the EMI date",
    "No contact",
    "When the due date keeps landing a few days before payday, moving it fixes the cause instead of chasing the bounce every month.",
  ],
  [
    "Self-service plan",
    "No contact",
    "Opens a resolution path the borrower can take in their own time, where they already are: the app, the portal, the next statement.",
  ],
  [
    "SMS with a pay link",
    "SMS",
    "Cures the forgot segment at a fraction of a call. Timed to the credit, not the calendar.",
  ],
  [
    "WhatsApp with a pay link",
    "WhatsApp",
    "The same cure on the channel most customers actually read, inside their consent.",
  ],
  ["Voice agent", "Voice", "Volume work in the early book: identity, amount, promise, objection."],
  [
    "Agent call",
    "Voice",
    "Hardship, disputes, settlements, and anything outside what an agent may do.",
  ],
  [
    "Field visit",
    "In person",
    "Expensive and often unanswered. Only from 31 days past due, above a minimum balance, when digital is exhausted.",
  ],
  [
    "Legal notice",
    "Legal",
    "A clock, not a conversation. Served by registered post, outside the contact cap, and still allowed under a legal hold.",
  ],
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
            capacity on them, and books their payment as the model's own success. PayInt is built to
            score the difference your action makes instead, and it shows its working on every
            decision.
          </>
        }
        secondary={{ label: "See the platform", href: "/platform/" }}
        proof={[
          "Built for uplift",
          "Vetoes before scoring",
          "Scored in money",
          "Every decision explained",
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
            recommends contacting self-curers. Until an uplift model has beaten the comparison
            group, PayInt scores from each borrower's own history and from rates learned on your
            book, and every decision says which.
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
              "For some accounts, contact makes things worse: a complaint, an opt-out, an escalation. Uplift can go negative, and an engine that cannot represent a negative cannot avoid it.",
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
              leave it alone. A propensity model measures the first and never looks at the second.
              Across most of a book the two are the same line, and that is exactly where the money
              gets spent for nothing.
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
                "All ten actions, each planned to a specific moment, because asking may-we-dial at 02:00 answers no for every customer alive.",
              ],
              [
                "Veto",
                "Consent, calling window, contact caps, cooling-off, third-party contact, holds, days-past-due stage, stale bank data, technical bounces and what the customer said on the last call.",
              ],
              ["Score", "Expected value in money for each surviving candidate."],
              ["Arbitrate", "One action wins, with the reasons that eliminated the others."],
              [
                "Log",
                "Every decision, including the blocked ones, with the probability it was chosen under. Searchable, exportable, and one click from its full trace.",
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
            Waiting evaluates to exactly zero, and anything that acts must also clear a small
            minimum value, so a recommended action is always a claim that doing something beats
            doing nothing on this account, today, by this much.
          </p>
        </div>
        <Rows
          items={[
            [
              "Timing is scored, not asked afterwards",
              "Each candidate is planned to a moment before it is vetoed. Digital nudges land near the salary credit when the failure was insufficient funds, calls prefer an hour this customer has actually answered at, and a field visit takes a day's notice and never lands on a Sunday.",
            ],
            [
              "Cost is real, not nominal",
              "Attempts per connect dominates the cost base and is usually unmeasured. At a 30% answer rate a connect costs 3.3 rings; at 15% it costs 6.7. Answer rates are learned from your own outcomes and bot-call cost is metered, while the rest of the cost table is yours to set, through review.",
            ],
            [
              "Fatigue is a term, not a policy afterthought",
              "Contact has a cost to the relationship as well as to the P&L. It is priced in the score, on top of the hard frequency cap that no score can override.",
            ],
            [
              "Book-level allocation, not just per-account",
              "Agent hours and field slots are finite. The allocation layer prices that scarcity every night, and it only starts steering decisions once it has cleared its own checks. It ships switched off.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="The action space"
        title={["Ten things to do,", "and one of them is nothing."]}
        lede="Silence is a first-class action with a real score, which is the only way an engine can ever recommend fewer contacts."
        wide
      >
        <Table
          className="table--tight"
          head={["Action", "Channel", "When it wins"]}
          rows={actionRows}
          caption="Mandates, field visits and legal notices land in supervisor queues with a Confirm and enact step, so a person signs off on anything that leaves the building. Re-presentation goes to your loan system as a work item unless a payment-rail adapter is connected."
        />
      </Section>
      <Section
        id="trace"
        eyebrow="The record"
        title={["Every decision,", "with its working shown."]}
        lede={
          <>
            Open any decision and the engine shows why it acted now, every option it weighed, and
            where each number came from. A language model can put that into plain words, but only
            with numbers the record already holds.
          </>
        }
      >
        <div className="tracegrid">
          <Rows
            items={[
              [
                "Why now",
                "The trigger, the facts it relied on, how fresh the bank feed was and which rules were in force.",
              ],
              [
                "Every option",
                "All ten actions, each scored or marked blocked before scoring, with the reason in plain language.",
              ],
              [
                "Where each number came from",
                "This borrower's history, a rate learned from recent outcomes, or the starting assumption. It says which.",
              ],
              [
                "What happened next",
                "The calls, messages, promises and payments that followed, and the version of every rule and model involved.",
              ],
            ]}
          />
          <Trace />
        </div>
      </Section>
      <Section
        eyebrow="The model's job"
        title={["The model explains.", "The engine decides."]}
        lede={
          <>
            There is a real and useful role for a language model around a collections decision.
            Making it is not that role.
          </>
        }
      >
        <div className="split">
          <div className="split__col rise" data-fx>
            <h3 className="split__h">What the model does</h3>
            <ul className="ticks ticks--yes">
              <li>Understands the customer on a call, and follows if they switch language</li>
              <li>Puts a decision into plain words, using only numbers from its record</li>
              <li>
                Proposes up to three setting changes a week, with the numbers behind each, for a
                person to approve
              </li>
              <li>Drafts a whisper a supervisor can send to a live agent</li>
            </ul>
          </div>
          <div className="split__col rise" data-fx>
            <h3 className="split__h">What it cannot do</h3>
            <ul className="ticks ticks--no">
              <li>Choose an action, or take any part in scoring, vetoes or arbitration</li>
              <li>Revive anything a gate blocked</li>
              <li>Change the channel or the moment an action was planned for</li>
              <li>Quote a settlement or approve a waiver</li>
              <li>State a figure the record does not contain</li>
            </ul>
          </div>
        </div>
        <p className="note rise" data-fx>
          The first is enforced by the build itself: the scoring, policy and arbitration code cannot
          import a language model. The last is enforced at runtime: an explanation containing a
          number the record does not hold is thrown away, and the rule-written text is shown
          instead.
        </p>
      </Section>
      <Section
        eyebrow="Stopping"
        title={["Eight reasons to stop", "get a row, not a label."]}
        lede={
          <>
            Hardship, dispute, complaint, bereavement, legal, cease-and-desist, deceased and
            no-upsell each place a hold on the account. A hold is a record the runtime reads, which
            is what binds an agent at 02:00 exactly as it binds a supervisor at noon.
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
              "A legal hold still permits a legal notice. A dispute hold still permits a specialist call about the dispute itself. A hardship hold allows nothing but waiting. Blanket silence is its own failure mode.",
            ],
            [
              "Releasing one takes two people",
              "Legal, cease-and-desist, deceased and bereavement holds need a second person to lift them. And what a customer says on a call can only take options away, never add one.",
            ],
            [
              "Offers come from what customers ask for",
              "Offers are never spoken on a collections call. A buying signal from a conversation becomes an offer only with a written suitability finding, goes out later by WhatsApp with marketing consent or to a relationship manager, and one in ten is held back to measure.",
            ],
            [
              "The ladder stops on its own",
              "A broken promise re-enters the engine the hour it breaks, with a cap of five attempts, a twelve-hour backoff and a repeat penalty. Following up forever is a bug, not persistence.",
            ],
          ]}
        />
      </Section>
      <Section
        eyebrow="Proving it"
        title={["A number nobody", "can argue with."]}
        lede="An engine that cannot be evaluated is a story. The measurement apparatus ships with it, and most of it runs on a schedule."
      >
        <Steps
          items={[
            [
              "Shadow first, always",
              "The engine runs and logs every decision, including the blocked ones, without acting. A fortnight of that tells you what it would have done and what it would have cost, before anything changes for a customer.",
            ],
            [
              "Rates that learn in the open",
              "Every night, reach and cure rates are re-learned from outcomes and shown side by side: what was assumed, what the engine now uses, and the evidence that moved it.",
            ],
            [
              "A genuine comparison group",
              "A randomised group gets only what policy requires. It is the only thing that separates lift from seasonality, and the platform will not report uplift without one.",
            ],
            [
              "Off-policy evaluation, every week",
              "A challenger is trained and estimated against logged decisions (importance sampling, self-normalised and doubly robust), so it can be compared before it ever touches a customer.",
            ],
            [
              "A promotion gate that says no by default",
              "A challenger needs a pre-registration signed by a second person and has to clear the gate. Silence from the gate means no.",
            ],
            [
              "Changes need a second person",
              "About twenty strategy settings, costs included, are edited as proposals with an estimated impact. A change applies only when someone other than its author approves it.",
            ],
          ]}
        />
        <Pull by="The promise behind the engine">
          Until a model has beaten the comparison group, the engine says so. On every decision.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What people ask", "about the engine."]}>
        <Faq items={faqs["/decision-engine/"]} />
      </Section>
      <More
        links={[
          ["/agents/", "The agents", "What carries out the decision, and what it may not do."],
          ["/platform/", "The platform", "How the whole pipeline runs."],
          ["/compliance/", "Compliance", "The vetoes, and the evidence they leave."],
        ]}
      />
      <Closing
        title={["Bring your book.", "We will score it."]}
        lede="In a walkthrough we run the engine over real accounts of yours in shadow mode and show you what it would have done, what it would have held back, and why."
        secondary={{ label: "Read the architecture", href: "/security/" }}
      />
    </>
  );
}
