import React from "react";
import { Closing, Faq, More, PageHero, Pull, Rows, Section, Table, Cols } from "../components/ui";
import { faqs } from "../data/faqs";
import { site } from "../site";

// The reference deployment as it ships: everything runs on infrastructure the
// customer controls; live speech and language services are called on the
// customer's own keys (or run self-hosted); the post-call models run offline.
function Topology() {
  return (
    <div className="diagram rise" data-fx>
      <div className="diagram__scroll">
        <svg viewBox="0 0 1200 552" role="img" aria-labelledby="archTitle archDesc">
          <title id="archTitle">PayInt reference deployment</title>
          <desc id="archDesc">
            Systems of record, the PayInt runtime and the channel edge run on infrastructure you
            control. Live speech and language services run on your own keys in your chosen region,
            or on self-hosted models. Post-call models run inside the runtime with no internet
            access.
          </desc>
          <rect className="dg-frame" x="28" y="60" width="930" height="456" rx="22" />
          <text className="dg-frame-label" x="54" y="94">
            YOUR INFRASTRUCTURE
          </text>
          <text className="dg-h" x="64" y="140">
            SYSTEMS OF RECORD
          </text>
          {["Core banking", "Loan management", "Bank data feeds", "Data warehouse"].map(
            (name, i) => (
              <g key={name}>
                <rect className="dg-box" x="64" y={160 + i * 74} width="184" height="56" rx="10" />
                <text className="dg-t" x="82" y={194 + i * 74}>
                  {name}
                </text>
              </g>
            ),
          )}
          <path className="dg-arrow dg-flow" d="M256 296 H292" />
          <path className="dg-arrow-head" d="M292 296 l-9 -5 v10 z" />
          <rect className="dg-core" x="300" y="128" width="352" height="360" rx="16" />
          <text className="dg-h dg-h--on" x="324" y="164">
            PAYINT RUNTIME
          </text>
          {[
            ["Agent runtime", "voice · WhatsApp · desktop"],
            ["Decision and policy engine", "ten actions, vetoes first"],
            ["Governance gates", "consent · hours · caps · identity"],
            ["Evidence and audit store", "hash-chained, re-checkable"],
          ].map(([name, sub], i) => (
            <g key={name}>
              <rect className="dg-inner" x="324" y={184 + i * 72} width="304" height="58" rx="9" />
              <text className="dg-t dg-t--on" x="342" y={209 + i * 72}>
                {name}
              </text>
              <text className="dg-s" x="342" y={228 + i * 72}>
                {sub}
              </text>
            </g>
          ))}
          <text className="dg-s dg-s--foot" x="324" y="472">
            Post-call models run in this box, offline.
          </text>
          <path className="dg-arrow dg-flow" d="M660 296 H700" />
          <path className="dg-arrow-head" d="M700 296 l-9 -5 v10 z" />
          <text className="dg-h" x="708" y="140">
            CHANNEL EDGE
          </text>
          {["Your carrier", "WhatsApp Business", "Agent desktop"].map((name, i) => (
            <g key={name}>
              <rect className="dg-box" x="708" y={160 + i * 74} width="196" height="56" rx="10" />
              <text className="dg-t" x="726" y={194 + i * 74}>
                {name}
              </text>
            </g>
          ))}
          <path className="dg-arrow dg-flow" d="M912 296 H1024" />
          <path className="dg-arrow-head" d="M1024 296 l-9 -5 v10 z" />
          <rect className="dg-box dg-box--out" x="1032" y="266" width="140" height="60" rx="10" />
          <text className="dg-t" x="1050" y="302">
            Your customer
          </text>
          <path className="dg-link" d="M652 440 H1024" />
          <path className="dg-arrow-head dg-arrow-head--link" d="M1024 440 l-9 -5 v10 z" />
          <text className="dg-s dg-s--link" x="712" y="430">
            your keys · your region
          </text>
          <rect className="dg-box dg-box--ai" x="1032" y="404" width="140" height="72" rx="10" />
          <text className="dg-t" x="1050" y="434">
            AI services
          </text>
          <text className="dg-s dg-s--dark" x="1050" y="456">
            or self-hosted
          </text>
        </svg>
      </div>
    </div>
  );
}

const reviewTopics = [
  "Data flows and sub-processors",
  "Identity and access",
  "Tenant isolation",
  "Redaction and retention",
  "DPDP subject rights",
  "Model and prompt versioning",
];

export function SecurityPage() {
  return (
    <>
      <PageHero
        eyebrow="Security and deployment"
        title={["You choose where it runs.", "You hold the keys."]}
        lede={
          <>
            PayInt ships as containers you run on your own servers or cloud account, behind
            Microsoft sign-in, with AI services billed to your own keys in the region you pick. The
            models that read every call afterwards run locally with no internet access, and the
            voice engine can run on self-hosted speech and language models where a deployment calls
            for it.
          </>
        }
        secondary={{ label: "Compliance and QA", href: "/compliance/" }}
        proof={[
          "Your servers or cloud",
          "Bring your own AI keys",
          "Local post-call models",
          "Row-level tenant isolation",
        ]}
      />
      <Section
        eyebrow="Reference deployment"
        title={["Standard topology,", "drawn honestly."]}
        lede="What runs inside your boundary, what it calls out to on your keys, and what never leaves."
      >
        <Topology />
        <Cols
          items={[
            [
              "What stays with you",
              "Customer records, recordings, transcripts and the evidence chain live in your database and storage. Personal-data detection, intent, sentiment and beep timing run on four local models with no internet access.",
            ],
            [
              "What calls out, on your keys",
              "Live speech recognition, voices and language models run on Azure OpenAI and Azure Speech under your own subscription and region by default. The voice engine can use other providers, or self-hosted models, per deployment.",
            ],
            [
              "How it lands",
              "Containers on your servers or cloud account, behind Microsoft Entra ID, with one contract for your core banking and loan data. Nothing starts dialling until an admin switches outbound on.",
            ],
          ]}
        />
      </Section>
      <Section eyebrow="Deployment models" title={["Three shapes,", "one product."]} wide>
        <Table
          head={["Model", "Where it runs", "What it suits"]}
          rows={[
            [
              "Your data centre",
              "Your servers and your change control, with AI services on your own keys.",
              "Institutions whose records have to stay in the building.",
            ],
            [
              "Your cloud account",
              "Your subscription, your region, your keys, your network policy.",
              "Teams already running a governed cloud estate who want the same isolation without the hardware.",
            ],
            [
              "Self-hosted models",
              "The voice engine on self-hosted speech and language endpoints, set up per deployment.",
              "Environments where sending call audio to a cloud AI service is not an option.",
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
                  "Records, recordings, transcripts and the evidence chain stay in your database and storage.",
                ],
                [
                  "Redaction",
                  "Transcripts masked as they are written; recordings beeped over identity and card values. The original plays only for roles cleared for it, and every play is logged.",
                ],
                [
                  "Encryption",
                  "Borrower phone numbers, emails and addresses are encrypted in the database, with a key-rotation script. TLS at the edge.",
                ],
                [
                  "Outbound events",
                  "No customer data leaves through a webhook until someone reviews the destination and a signed test delivery succeeds. Payloads carry no phone numbers or transcripts.",
                ],
              ]}
            />
          </div>
          <div className="sec__col rise" data-fx>
            <h3>Identity and access</h3>
            <Rows
              items={[
                [
                  "Single sign-on",
                  "Microsoft Entra ID. No local passwords, guest and personal accounts refused, and a first-time user gets no role until invited.",
                ],
                [
                  "Authorisation",
                  "Role and scope checks on every module and every export. Routes that are not registered are denied, and the build checks the coverage.",
                ],
                [
                  "Separation",
                  "Tenant isolation enforced by Postgres row-level security. A deployment will not start with isolation, append-only audit or data encryption switched off.",
                ],
                [
                  "Session evidence",
                  "Every export and every playback of a raw recording is logged, with who and when.",
                ],
              ]}
            />
          </div>
          <div className="sec__col rise" data-fx>
            <h3>Models</h3>
            <Rows
              items={[
                [
                  "Your keys",
                  "Azure OpenAI and Azure Speech on your own subscription by default. The voice engine can use other providers, or self-hosted models, per agent.",
                ],
                [
                  "Local where it matters",
                  "Personal-data detection, intent, sentiment and beep timing run on four pinned models inside your deployment, with no internet access.",
                ],
                [
                  "Versioned",
                  "The agent version is recorded on every call, and model versions on every post-call result and planning decision.",
                ],
                [
                  "No training on your data",
                  "The engine's own models learn from your book inside your deployment. Cloud AI services run under your own agreement with the provider.",
                ],
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
            Ask for the architecture review early. What can be attested depends on the deployment
            and on who hosts it, which is a real distinction rather than a hedge, so we walk through
            it for your setup.
          </>
        }
      >
        <div className="standards rise" data-fx>
          <p className="standards__lab">What the review covers</p>
          <ul>
            {reviewTopics.map((topic) => (
              <li key={topic}>{topic}</li>
            ))}
          </ul>
        </div>
        <Pull by="The sentence this page exists to support">
          Every service that touches a customer of ours runs on our keys, in our region, under our
          contract.
        </Pull>
      </Section>
      <Section eyebrow="Questions" title={["What security teams", "ask first."]}>
        <Faq items={faqs["/security/"]} />
      </Section>
      <More
        links={[
          ["/compliance/", "Compliance and QA", "Gates, scoring and the evidence trail."],
          ["/platform/", "The platform", "How the whole pipeline runs."],
          ["/agents/", "The agents", "What carries out the work, and what it may not do."],
        ]}
      />
      <Closing
        title={["Send us your", "architecture review."]}
        lede="We would rather answer the long questionnaire early than discover a blocker in month three. Send it over and we will fill it in before the first call."
        secondary={{ label: "Book a walkthrough", href: "/demo/" }}
        primary={{ label: "Email the architecture team", href: `mailto:${site.email}` }}
      />
    </>
  );
}
