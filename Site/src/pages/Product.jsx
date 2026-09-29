import React from "react";
import { Closing, More, PageHero, Rows, Section } from "../components/ui";
import { moduleCount, moduleGroups } from "../data/modules";

export function ProductPage() {
  return (
    <>
      <PageHero
        eyebrow="Product"
        title={[`${moduleCount} modules.`, "One governed pipeline."]}
        lede={
          <>
            The screens a collections floor actually runs on — the queue, the account, the promise,
            the dispute, the recording, the scorecard and the studio that builds the agents. Every
            one of them writes to the same customer record and the same evidence log, which is the
            difference between a platform and a folder of tools.
          </>
        }
        secondary={{
          label: "How it fits together",
          href: "/platform/",
        }}
      />
      {moduleGroups.map((f, a) => (
        <Section
          id={f.name.toLowerCase().replace(/[^a-z]+/g, "-")}
          eyebrow={`0${a + 1} — ${f.items.length} modules`}
          title={[f.name]}
          lede={f.note}
          key={f.name}
        >
          <Rows items={f.items.map(([r, l]) => [r, l])} />
        </Section>
      ))}
      <More
        links={[
          [
            "/decision-engine/",
            "Decision intelligence",
            "The module that decides what the others do.",
          ],
          ["/agents/", "Voice Studio", "Workflows, tools, knowledge and releases."],
          ["/compliance/", "Compliance and QA", "Audit trail, consent, redaction and scorecards."],
        ]}
      />
      <Closing
        title={["A tour, not", "a slide deck."]}
        lede="We will open the console on a book that looks like yours and work one account from the failed payment to the written promise."
        secondary={{
          label: "How we price it",
          href: "/pricing/",
        }}
      />
    </>
  );
}
