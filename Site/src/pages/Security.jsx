import React from "react";
import { Closing, Cols, Faq, More, PageHero, Pull, Rows, Section, Table } from "../components/ui";
import { faqs } from "../data/faqs";
import { site } from "../site";

function Topology() {
  return (
    <div className="diagram rise" data-fx>
      <div className="diagram__scroll">
        <svg viewBox="0 0 1200 552" role="img" aria-labelledby="archTitle archDesc">
          <title id="archTitle">PayInt reference deployment</title>
          <desc id="archDesc">
            Systems of record, the PayInt runtime and the channel edge all sit inside the customer
            perimeter. Only the channel edge reaches the end customer. No vendor cloud is in the
            path.
          </desc>
          <rect className="dg-frame" x="28" y="60" width="930" height="456" rx="22" />
          <text className="dg-frame-label" x="54" y="94">
            YOUR PERIMETER
          </text>
          <text className="dg-h" x="64" y="140">
            SYSTEMS OF RECORD
          </text>
          {["Core banking", "Loan management", "CRM and case", "Data warehouse"].map((f, a) => (
            <g key={f}>
              <rect className="dg-box" x="64" y={160 + a * 74} width="184" height="56" rx="10" />
              <text className="dg-t" x="82" y={194 + a * 74}>
                {f}
              </text>
            </g>
          ))}
          <path className="dg-arrow" d="M256 296 H292" />
          <path className="dg-arrow-head" d="M292 296 l-9 -5 v10 z" />
          <rect className="dg-core" x="300" y="128" width="352" height="360" rx="16" />
          <text className="dg-h dg-h--on" x="324" y="164">
            PAYINT RUNTIME
          </text>
          {[
            ["Agent runtime", "voice · messaging · desktop"],
            ["Decision and policy engine", "uplift scoring, locked policy"],
            ["Governance gates", "consent · hours · frequency · authority"],
            ["Evidence and audit store", "immutable, replayable"],
          ].map(([f, a], r) => (
            <g key={f}>
              <rect className="dg-inner" x="324" y={184 + r * 72} width="304" height="58" rx="9" />
              <text className="dg-t dg-t--on" x="342" y={209 + r * 72}>
                {f}
              </text>
              <text className="dg-s" x="342" y={228 + r * 72}>
                {a}
              </text>
            </g>
          ))}
          <text className="dg-s dg-s--foot" x="324" y="472">
            Models are self-hosted in this box.
          </text>
          <path className="dg-arrow" d="M660 296 H700" />
          <path className="dg-arrow-head" d="M700 296 l-9 -5 v10 z" />
          <text className="dg-h" x="708" y="140">
            CHANNEL EDGE
          </text>
          {["SIP / PSTN trunk", "Messaging gateway", "Agent desktop"].map((f, a) => (
            <g key={f}>
              <rect className="dg-box" x="708" y={160 + a * 74} width="196" height="56" rx="10" />
              <text className="dg-t" x="726" y={194 + a * 74}>
                {f}
              </text>
            </g>
          ))}
          <path className="dg-arrow" d="M912 296 H1024" />
          <path className="dg-arrow-head" d="M1024 296 l-9 -5 v10 z" />
          <rect className="dg-box dg-box--out" x="1032" y="266" width="140" height="60" rx="10" />
          <text className="dg-t" x="1050" y="302">
            Your customer
          </text>
          <rect className="dg-ghost" x="1032" y="404" width="140" height="58" rx="10" />
          <text className="dg-t dg-t--ghost" x="1050" y="438">
            Vendor cloud
          </text>
          <path className="dg-strike" d="M1042 452 L1162 414" />
          <text className="dg-s dg-s--ghost" x="1032" y="486">
            Not in the path.
          </text>
        </svg>
      </div>
    </div>
  );
}
const standards = [
  "ISO 27001 controls",
  "SOC 2 control mapping",
  "Payment-card scope reduction",
  "Data residency and subject rights",
  "Model and prompt versioning",
  "Recording retention and legal hold",
];
export function SecurityPage() {
  return (
    <>
      <PageHero
        eyebrow="Security and deployment"
        title={["The whole runtime sits", "inside your perimeter."]}
        lede={
          <>
            Containers on your estate, behind your identity provider, on your keys, over your
            trunks. The customer records, the recordings, the transcripts, the embeddings and the
            model weights stay where they already are — because there is no vendor cloud in the path
            to send them to.
          </>
        }
        secondary={{
          label: "Compliance and QA",
          href: "/compliance/",
        }}
        proof={[
          "On-premise by default",
          "Air-gapped option",
          "Your telephony contracts",
          "Self-hosted models",
        ]}
      />
      <Section
        eyebrow="Reference deployment"
        title={["Standard topology,", "drawn honestly."]}
        lede="Private-cloud and air-gapped variants change where the boundary is drawn, never what crosses it."
      >
        <Topology />
        <Cols
          items={[
            [
              "What never leaves",
              "Customer records, recordings, transcripts, embeddings and model weights. There is no scoring round trip to a vendor, so there is nothing to send and nothing to intercept.",
            ],
            [
              "What you keep",
              "Your telephony contracts, your data residency, your retention schedule and your change-control process. PayInt deploys into them rather than around them.",
            ],
            [
              "How it lands",
              "Containers on your Kubernetes or VM estate, behind your identity provider, with read paths into the core banking, loan management and warehouse systems you already run.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Deployment models" title={["Three shapes,", "one product."]} wide>
        <Table
          head={["Model", "Where it runs", "What it suits"]}
          rows={[
            [
              "On-premise",
              "Your data centre, your Kubernetes or VM estate, your change control.",
              "The default. Institutions whose data cannot leave the building, and whose auditors want to walk to the rack.",
            ],
            [
              "Private cloud",
              "Your subscription, your region, your keys, your network policy.",
              "Institutions already operating a governed cloud estate who want the same isolation without the hardware.",
            ],
            [
              "Air-gapped",
              "No egress at all. Updates arrive as signed bundles your team reviews and applies.",
              "The highest-sensitivity environments, and jurisdictions where egress is a licensing question rather than a preference.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Controls" title={["Data, identity", "and evidence."]}>
        <div className="sec">
          <div className="sec__col rise" data-fx>
            <h3>Data</h3>
            <Rows
              items={[
                [
                  "Residency",
                  "Records, recordings and transcripts never leave the boundary you draw.",
                ],
                [
                  "Redaction",
                  "Transcripts masked as they are written; recordings beeped over identity and card values. The original plays only for roles cleared for it, and every play is logged.",
                ],
                ["Encryption", "In transit and at rest, on keys you hold and can rotate."],
                ["Retention", "Your schedule per record type, with evidence of deletion."],
              ]}
            />
          </div>
          <div className="sec__col rise" data-fx>
            <h3>Identity and access</h3>
            <Rows
              items={[
                ["Single sign-on", "SAML or OIDC against your provider. No local password store."],
                ["Authorisation", "Role and scope checks on every module and every export."],
                ["Separation", "Tenant isolation for agency floors, enforced in the data layer."],
                ["Session evidence", "Who looked at what, and who exported it."],
              ]}
            />
          </div>
          <div className="sec__col rise" data-fx>
            <h3>Models</h3>
            <Rows
              items={[
                [
                  "Self-hosted",
                  "Speech and language models run in your deployment, on your hardware.",
                ],
                [
                  "Versioned",
                  "Model and prompt versions are recorded against every decision they touched.",
                ],
                [
                  "No training on your data",
                  "Weights ship to you. Nothing learned from your book leaves without a separate agreement.",
                ],
                ["Offline updates", "Signed bundles, reviewable, on your schedule."],
              ]}
            />
          </div>
        </div>
      </Section>
      <Section
        eyebrow="Assurance"
        title={["What to ask us for", "before you sign."]}
        lede={
          <>
            Controls are mapped to the frameworks below. Attestation status depends on the
            deployment and on which party hosts it, which is a real distinction rather than a hedge
            — ask for the current control pack and we will send it with the architecture review.
          </>
        }
      >
        <div className="standards rise" data-fx>
          <p className="standards__lab">Controls mapped to</p>
          <ul>
            {standards.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
        <Pull by="The sentence this page exists to support">
          Nothing about a customer of ours crosses a boundary we do not control.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What security teams", "ask first."]}>
        <Faq items={faqs["/security/"]} />
      </Section>
      <More
        links={[
          ["/compliance/", "Compliance and QA", "Gates, scoring and the evidence trail."],
          ["/platform/", "The platform", "How the whole pipeline runs."],
          ["/pricing/", "Pricing", "What a deployment and a pilot cost to run."],
        ]}
      />
      <Closing
        title={["Send us your", "architecture review."]}
        lede="We would rather answer the long questionnaire early than discover a blocker in month three. Send it over and we will fill it in before the first call."
        secondary={{
          label: "Book a walkthrough",
          href: "/demo/",
        }}
        primary={{
          label: "Email the architecture team",
          href: `mailto:${site.email}`,
        }}
      />
    </>
  );
}
