import React from "react";
import { moduleCount, moduleGroups } from "../data/modules";
import { isStill, useIsoLayoutEffect } from "../lib/motion";
import { site } from "../site";

const SCRUB_GAIN = 0.8,
  SCRUB_EPSILON = 1 / 48,
  HERO_VIDEO = "/videos/hero-bee.mp4",
  HERO_POSTER = "/videos/hero-bee.jpg",
  HERO_GREETING = "Hey there, meet A.P.I.S,",
  HERO_SYSTEM = "Beeonix's Autonomous Payment Intelligence System",
  HERO_LINE =
    "Glad you stopped in. Every account you hold is getting colder. Which one should we work first?",
  heroPills = [
    {
      label: "Sign in to PayInt",
      href: "/login",
    },
    {
      label: "See how a bounce becomes a call",
      href: "/platform/",
    },
    {
      label: "Score a next-best treatment",
      href: "/decision-engine/",
    },
    {
      label: "Read the audit record",
      href: "/compliance/",
    },
  ];
function useTyped(f, a = 38, r = 600) {
  const [l, s] = React.useState(f),
    [c, d] = React.useState(true);
  return (
    useIsoLayoutEffect(() => {
      if (isStill()) return;
      (s(""), d(false));
      let m = 0,
        g = 0;
      const y = window.setTimeout(() => {
        g = window.setInterval(() => {
          ((m += 1), s(f.slice(0, m)), m >= f.length && (window.clearInterval(g), d(true)));
        }, a);
      }, r);
      return () => {
        (window.clearTimeout(y), window.clearInterval(g));
      };
    }, [f, a, r]),
    {
      displayed: l,
      done: c,
    }
  );
}
function useScrubVideo(f) {
  React.useEffect(() => {
    const a = f.current;
    if (!a) return;
    let r = null,
      l = 0,
      s = false,
      c = 0,
      d = true;
    const m = isStill(),
      g = () => (Number.isFinite(a.duration) ? a.duration : 0),
      y = () => {
        c = 0;
        const O = g();
        !O ||
          s ||
          Math.abs(a.currentTime - l) < SCRUB_EPSILON ||
          ((s = true), (a.currentTime = Math.min(O, Math.max(0, l))));
      },
      v = () => {
        c || (c = requestAnimationFrame(y));
      },
      b = () => {
        ((l = g() / 2), (a.currentTime = l));
      },
      S = (O) => {
        if (!d) {
          r = null;
          return;
        }
        if (r === null) {
          r = O.clientX;
          return;
        }
        const H = O.clientX - r;
        r = O.clientX;
        const U = g();
        !U ||
          H === 0 ||
          ((l = Math.min(U, Math.max(0, l + (H / window.innerWidth) * SCRUB_GAIN * U))), v());
      },
      x = () => {
        ((s = false), Math.abs(a.currentTime - l) >= SCRUB_EPSILON && v());
      },
      E = () => {
        r = null;
      };
    if (
      (m || a.addEventListener("seeked", x),
      a.readyState >= HTMLMediaElement.HAVE_METADATA
        ? b()
        : a.addEventListener("loadedmetadata", b),
      m)
    )
      return () => a.removeEventListener("loadedmetadata", b);
    const w = new IntersectionObserver(([O]) => {
      ((d = O.isIntersecting), d || E());
    });
    return (
      w.observe(a),
      window.addEventListener("mousemove", S, {
        passive: true,
      }),
      window.addEventListener("blur", E),
      document.addEventListener("mouseleave", E),
      () => {
        (cancelAnimationFrame(c),
          w.disconnect(),
          a.removeEventListener("loadedmetadata", b),
          a.removeEventListener("seeked", x),
          window.removeEventListener("mousemove", S),
          window.removeEventListener("blur", E),
          document.removeEventListener("mouseleave", E));
      }
    );
  }, [f]);
}
function CopyIcon({ copied: f }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      {f ? (
        <path
          d="M1.5 6.4 4.3 9.2 10.5 3"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ) : (
        <>
          <rect x="4" y="4" width="7" height="7" rx="1.4" stroke="currentColor" strokeWidth="1.1" />
          <path
            d="M8 1.5H2.4A1.4 1.4 0 0 0 1 2.9V8.5"
            stroke="currentColor"
            strokeWidth="1.1"
            strokeLinecap="round"
          />
        </>
      )}
    </svg>
  );
}
function HomeHero() {
  const f = React.useRef(null),
    { displayed: a, done: r } = useTyped(HERO_LINE),
    [l, s] = React.useState(false),
    [c, d] = React.useState(false);
  (useScrubVideo(f),
    useIsoLayoutEffect(() => {
      if (isStill()) {
        s(true);
        return;
      }
      const g = window.setTimeout(() => s(true), 400);
      return () => window.clearTimeout(g);
    }, []),
    React.useEffect(() => {
      if (!c) return;
      const g = window.setTimeout(() => d(false), 1800);
      return () => window.clearTimeout(g);
    }, [c]));
  const m = async () => {
    try {
      (await navigator.clipboard.writeText(site.email), d(true));
    } catch {}
  };
  return (
    <section className="scrub" id="top">
      <video
        ref={f}
        className="scrub__video"
        src={HERO_VIDEO}
        poster={HERO_POSTER}
        muted
        playsInline
        preload="auto"
        tabIndex={-1}
        aria-hidden="true"
      />
      <div className="scrub__scrim" aria-hidden="true" />
      <div className="scrub__in">
        <p className="scrub__label">
          {HERO_GREETING}
          <br />
          {HERO_SYSTEM}
        </p>
        <h1 className="scrub__type">
          {a}
          {!r && <span className="scrub__caret" aria-hidden="true" />}
        </h1>
        <div className={`scrub__pills${l ? " is-on" : ""}`} data-hero-cta>
          {heroPills.map((g) => (
            <a className="pill" href={g.href} key={g.href}>
              {g.label}
            </a>
          ))}
          <button className="pill pill--out" type="button" onClick={m}>
            <span>
              {"Reach us: "}
              <span className="pill__mail">{site.email}</span>
            </span>
            <CopyIcon copied={c} />
            <span className="u-sr">{c ? "Address copied" : "Copy address"}</span>
          </button>
        </div>
      </div>
    </section>
  );
}
const features = [
  {
    id: "f1",
    title: "Bounce to contact in minutes",
    body: "A mandate fails at 9:04. The event reaches us the same minute it hits the bank, and an agent is on the phone before tonight's batch file would even have been written.",
    notes: ["Real-time mandate hooks", "No overnight batch", "Auto-retry windows"],
  },
  {
    id: "f2",
    title: "Every promise in writing, before the call ends",
    body: "The promise to pay is confirmed on the call, stamped, and delivered as a written record while the customer is still on the line — with a pay link they can act on immediately.",
    notes: ["In-call pay link", "Written PTP", "Immutable record"],
  },
  {
    id: "f3",
    title: "Decision intelligence, not the model",
    body: "Next-best-treatment comes from a locked policy engine scoring uplift — who repays because you acted — never from a language model's opinion about what sounds reasonable.",
    notes: ["Uplift scoring", "Locked engine", "Full decision log"],
  },
  {
    id: "f4",
    title: "Consent and authority are hard gates",
    body: "Do-not-contact status, permitted contact hours, frequency caps and settlement authority are enforced before a call is allowed to exist. The agent cannot negotiate past a gate, because it never sees one open.",
    notes: ["Do-not-contact + hours", "Cross-channel caps", "Live authority matrix"],
  },
  {
    id: "f5",
    title: "100% of calls scored, not sampled",
    body: "Not a two percent sample read next week. Every call is graded minutes after it ends: rules on what the call actually did first, small models running inside your perimeter next, and a language-model judge only for the criteria they could not settle. Every score shows who decided it and on what evidence.",
    notes: ["Every call", "Evidence per score", "Zero sampling"],
  },
  {
    id: "f6",
    title: "Compose the agent in Voice Studio.",
    body: "Workflows, tools and knowledge — drafted in the studio or from Claude and Codex over MCP. A person still publishes. The compliance rails are not a component on the canvas — they are the floor the canvas sits on.",
    notes: ["Voice Studio", "MCP drafts", "Non-removable rails"],
  },
];
function HomeFeatures() {
  return (
    <section className="section" id="platform">
      <div className="shell">
        <div className="section__head">
          <p className="eyebrow rise" data-fx>
            Platform
          </p>
          <h2 className="display" data-split>
            <span className="line">
              <i>Six things a collections</i>
            </span>
            <span className="line">
              <i>floor does every day.</i>
            </span>
          </h2>
          <p className="lede rise" data-fx>
            Bounce to contact, promise to paper, decision to action — worked by Voice Studio agents,
            governed by policy engines the agents cannot talk their way past.
          </p>
        </div>
        <div className="features">
          {features.map((f, a) => (
            <article className={`feature${a % 2 === 1 ? " feature--flip" : ""}`} key={f.id}>
              <div className="feature__copy">
                <p className="feature__index rise" data-fx>
                  {String(a + 1).padStart(2, "0")}
                </p>
                <h3 className="rise" data-fx>
                  {f.title}
                </h3>
                <p className="rise" data-fx>
                  {f.body}
                </p>
                <ul className="feature__notes rise" data-fx>
                  {f.notes.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
              <div className="feature__media rise" data-fx>
                <video
                  src={`/videos/${f.id}.mp4`}
                  poster={`/videos/${f.id}.jpg`}
                  muted
                  loop
                  playsInline
                />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
const PILLAR_PREVIEW = 8;
function HomeModules() {
  return (
    <section className="platform" id="modules">
      <div className="platform__in">
        <div className="platform__head">
          <p className="eyebrow rise" data-fx>
            The product
          </p>
          <h2 className="display" data-split>
            <span className="line">
              <i>
                {moduleCount}
                {" modules."}
              </i>
            </span>
            <span className="line">
              <i>One governed pipeline.</i>
            </span>
          </h2>
          <p className="platform__lede rise" data-fx>
            Voice, messaging and the workspace your collectors already live in — Voice Studio to
            compose them, a customer record that remembers everything, and an audit trail that can
            answer for all of it.
          </p>
        </div>
        <div className="platform__grid">
          {moduleGroups.map((f) => (
            <div className="pillar rise" data-fx key={f.name}>
              <h3 className="pillar__name">{f.name}</h3>
              <p className="pillar__desc">{f.note}</p>
              <ul className="pillar__list">
                {f.items.slice(0, PILLAR_PREVIEW).map(([a]) => (
                  <li key={a}>{a}</li>
                ))}
                {f.items.length > PILLAR_PREVIEW ? (
                  <li>
                    <a href={`/product/#${f.name.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
                      {"and "}
                      {f.items.length - PILLAR_PREVIEW}
                      {" more"}
                    </a>
                  </li>
                ) : null}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
const homeMetrics = [
  {
    to: 4,
    unit: "min",
    k: "Median bounce to first live contact",
  },
  {
    to: 100,
    unit: "%",
    k: "Of calls scored, not sampled",
  },
  {
    to: 48,
    unit: "h",
    k: "Full book coverage window",
  },
  {
    to: 0,
    unit: "",
    k: "Consent and calling-hour breaches",
  },
];
function HomeMetrics() {
  return (
    <section className="section">
      <div className="shell">
        <div className="section__head">
          <p className="eyebrow rise" data-fx>
            The math
          </p>
          <h2 className="display" data-split>
            <span className="line">
              <i>The profit lever is</i>
            </span>
            <span className="line">
              <i>delay, not dialogue.</i>
            </span>
          </h2>
          <p className="lede rise" data-fx>
            A bounce worked in the first hour cures at a different rate than the same bounce worked
            on Thursday. Most floors lose the money in the queue, not on the call.
          </p>
        </div>
        <div className="metrics">
          {homeMetrics.map((f) => (
            <div className="metric rise" data-fx key={f.k}>
              <p className="metric__n">
                <span data-count={f.to}>0</span>
                {f.unit ? <span>{f.unit}</span> : null}
              </p>
              <p className="metric__k">{f.k}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
const trustItems = [
  {
    h: "It runs inside your bank",
    p: "On-premise by default. Models, recordings and customer data never leave the perimeter, and nothing is shipped to a vendor cloud for scoring.",
  },
  {
    h: "Every decision is answerable",
    p: "Each action carries the policy version, the score, the gate results and the transcript. When the auditor asks why this customer was called at that hour, there is one answer.",
  },
  {
    h: "The same factory for insurance",
    p: "Renewals, lapsed policies and premium recovery run on the identical engine — different offers and gates, the same governed pipeline.",
  },
];
function HomeTrust() {
  return (
    <section className="section" id="trust">
      <div className="shell">
        <div className="section__head">
          <p className="eyebrow rise" data-fx>
            Deployment
          </p>
          <h2 className="display" data-split>
            <span className="line">
              <i>Built for a floor</i>
            </span>
            <span className="line">
              <i>that gets audited.</i>
            </span>
          </h2>
        </div>
        <div className="trust">
          {trustItems.map((f) => (
            <div className="trust__item rise" data-fx key={f.h}>
              <h4>{f.h}</h4>
              <p>{f.p}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
function HomeClosing() {
  return (
    <div className="shell" id="closing">
      <section className="closing">
        <h2 className="display" data-split>
          <span className="line">
            <i>See a bounce become</i>
          </span>
          <span className="line">
            <i>a conversation.</i>
          </span>
        </h2>
        <p className="lede rise" data-fx>
          Thirty minutes, your book, your rules. We will run one live account end to end.
        </p>
        <div className="closing__row rise" data-fx>
          <a className="btn btn--primary" href="/demo/">
            Book a walkthrough
          </a>
          <a className="btn btn--quiet" href="/security/">
            Read the architecture
          </a>
        </div>
      </section>
    </div>
  );
}
export function HomePage() {
  return (
    <>
      <HomeHero />
      <div className="below">
        <HomeFeatures />
        <HomeModules />
        <HomeMetrics />
        <HomeTrust />
        <HomeClosing />
      </div>
    </>
  );
}
