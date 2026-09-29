import React from "react";
import { PageHero, Rows, Section, Steps } from "../components/ui";
import { site } from "../site";

const bookSizes = [
  "Under 50,000 accounts",
  "50,000 – 250,000 accounts",
  "250,000 – 1 million accounts",
  "Over 1 million accounts",
  "Insurance book",
];
export function DemoPage() {
  const [f, a] = React.useState("idle");
  async function r(l) {
    l.preventDefault();
    const s = l.currentTarget,
      c = new FormData(s);
    if (c.get("company_website")) return;
    const m = ["name", "email", "company", "role", "book", "notes"].map(
      (g) => `${g}: ${String(c.get(g) ?? "")}`,
    ).join(`
`);
    ((location.href = `mailto:${site.email}?subject=${encodeURIComponent("Walkthrough request")}&body=${encodeURIComponent(m)}`),
      a("mail"));
  }
  return (
    <>
      <PageHero
        eyebrow="Book a walkthrough"
        title={["See a bounce become", "a conversation."]}
        lede={
          <>
            Thirty minutes, your book, your rules. We run one live account end to end — the trigger,
            the gates, the decision, the call, and the audit record it leaves behind. No slide deck,
            and no discovery call before the product appears.
          </>
        }
        primary={{
          label: "Jump to the form",
          href: "#form",
        }}
        secondary={{
          label: "Read the architecture first",
          href: "/security/",
        }}
      />
      <Section eyebrow="The half hour" title={["What we will", "actually do."]}>
        <Steps
          items={[
            [
              "Take a failed payment through the whole pipeline",
              "From the event arriving to the case opening, the gates clearing, the engine choosing an action and the agent placing the call — on a book that looks like yours.",
            ],
            [
              "Try to break the agent",
              "You pick the objection. Ask it for a waiver it cannot give, a settlement it cannot quote, or a call outside permitted hours, and watch what it does instead.",
            ],
            [
              "Open the record afterwards",
              "The policy version, the gate results, the score, the recording and the transcript — the thing your auditor would actually ask for.",
            ],
            [
              "Talk about your book, not ours",
              "Bucket mix, channel mix, agency arrangements and the deployment model. If a pilot makes sense, you leave with a scope and a number.",
            ],
          ]}
        />
      </Section>
      <Section id="form" eyebrow="Get in touch" title={["Tell us what", "to bring."]}>
        <div className="formgrid">
          <form className="enquiry rise" data-fx onSubmit={r}>
            <div className="enquiry__row">
              <label>
                <span>Name</span>
                <input name="name" type="text" required autoComplete="name" />
              </label>
              <label>
                <span>Work email</span>
                <input name="email" type="email" required autoComplete="email" />
              </label>
            </div>
            <div className="enquiry__row">
              <label>
                <span>Organisation</span>
                <input name="company" type="text" required autoComplete="organization" />
              </label>
              <label>
                <span>Role</span>
                <input name="role" type="text" autoComplete="organization-title" />
              </label>
            </div>
            <label>
              <span>Book size</span>
              <select name="book" defaultValue="">
                <option value="" disabled>
                  Select one
                </option>
                {bookSizes.map((l) => (
                  <option value={l} key={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>What would you like to see?</span>
              <textarea
                name="notes"
                rows={4}
                placeholder="A bucket, a bottleneck, or the audit question you could not answer last year."
              />
            </label>
            <input
              className="enquiry__trap"
              name="company_website"
              tabIndex={-1}
              autoComplete="off"
              aria-hidden="true"
            />
            <div className="enquiry__foot">
              <button className="btn btn--primary" type="submit" disabled={f === "sending"}>
                {f === "sending" ? "Sending…" : "Request a walkthrough"}
              </button>
              <p className="enquiry__note">
                We use what you send here to arrange the walkthrough and nothing else. No
                newsletter, no list.
              </p>
            </div>
            <p className="enquiry__status" role="status">
              {f === "sent"
                ? "Thank you — we will reply within one working day."
                : f === "mail"
                  ? "Your mail client should have opened with the details filled in. If it did not, send them to " +
                    site.email
                  : ""}
            </p>
          </form>
          <aside className="enquiry__aside rise" data-fx>
            <h3>Or go straight to a person</h3>
            <p>
              If you would rather skip the form, write to{" "}
              <a href={`mailto:${site.email}`}>{site.email}</a>
              {" with your book size and what you want to see. It reaches the same three people."}
            </p>
            <Rows
              items={[
                [
                  "Security review",
                  "Send the questionnaire early and we will return it before the first call.",
                ],
                [
                  "Procurement",
                  "Pricing is quoted on book size, channel mix and deployment model.",
                ],
                [
                  "Analysts and press",
                  "Same address. We will point you at the architecture notes.",
                ],
              ]}
            />
          </aside>
        </div>
      </Section>
    </>
  );
}
