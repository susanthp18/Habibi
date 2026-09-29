import React from "react";
import { moduleCount, moduleGroups } from "../data/modules";
import { isStill, useIsoLayoutEffect } from "../lib/motion";
import { site } from "../site";

/** How far one full-width mouse sweep scrubs through the hero video (share of its length). */
const SCRUB_GAIN = 0.8;
/** Seeks smaller than one frame at 48 fps are skipped. */
const SCRUB_EPSILON = 1 / 48;
const HERO_VIDEO = "/videos/hero-bee.mp4";
const HERO_POSTER = "/videos/hero-bee.jpg";
const HERO_GREETING = "Hey there, meet A.P.I.S.,";
const HERO_SYSTEM = "Beeonix's Autonomous Payment Intelligence System";
const HERO_TITLE = "Collections that move the hour the account does.";
const HERO_LINE =
  "Glad you stopped in. Every account you hold is getting colder. Which one should we work first?";
const HERO_NEWS = {
  label: "Supervisors can now listen, whisper and take over live calls",
  href: "/agents/#supervision",
};
const heroPills = [
  { label: "Sign in to PayInt", href: "/login" },
  { label: "Follow a bounce to a promise", href: "/platform/" },
  { label: "See why the engine picks an action", href: "/decision-engine/" },
  { label: "Read the audit record", href: "/compliance/" },
];

/** Types `text` out a character at a time; shows it whole for reduced motion and ?still. */
function useTyped(text, stepMs = 38, delayMs = 600) {
  const [shown, setShown] = React.useState(text);
  const [done, setDone] = React.useState(true);
  useIsoLayoutEffect(() => {
    if (isStill()) return;
    setShown("");
    setDone(false);
    let count = 0;
    let interval = 0;
    const timeout = window.setTimeout(() => {
      interval = window.setInterval(() => {
        count += 1;
        setShown(text.slice(0, count));
        if (count >= text.length) {
          window.clearInterval(interval);
          setDone(true);
        }
      }, stepMs);
    }, delayMs);
    return () => {
      window.clearTimeout(timeout);
      window.clearInterval(interval);
    };
  }, [text, stepMs, delayMs]);
  return { displayed: shown, done };
}

/** The hero bee follows the mouse: horizontal movement scrubs the video back and forth. */
function useScrubVideo(ref) {
  React.useEffect(() => {
    const video = ref.current;
    if (!video) return;
    let lastX = null;
    let target = 0;
    let seeking = false;
    let frame = 0;
    let visible = true;
    const still = isStill();
    const duration = () => (Number.isFinite(video.duration) ? video.duration : 0);
    const seek = () => {
      frame = 0;
      const length = duration();
      if (!length || seeking || Math.abs(video.currentTime - target) < SCRUB_EPSILON) return;
      seeking = true;
      video.currentTime = Math.min(length, Math.max(0, target));
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(seek);
    };
    const centre = () => {
      target = duration() / 2;
      video.currentTime = target;
    };
    const onMove = (event) => {
      if (!visible) {
        lastX = null;
        return;
      }
      if (lastX === null) {
        lastX = event.clientX;
        return;
      }
      const dx = event.clientX - lastX;
      lastX = event.clientX;
      const length = duration();
      if (!length || dx === 0) return;
      target = Math.min(
        length,
        Math.max(0, target + (dx / window.innerWidth) * SCRUB_GAIN * length),
      );
      schedule();
    };
    const onSeeked = () => {
      seeking = false;
      if (Math.abs(video.currentTime - target) >= SCRUB_EPSILON) schedule();
    };
    const reset = () => {
      lastX = null;
    };
    if (!still) video.addEventListener("seeked", onSeeked);
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) centre();
    else video.addEventListener("loadedmetadata", centre);
    if (still) return () => video.removeEventListener("loadedmetadata", centre);
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      if (!visible) reset();
    });
    observer.observe(video);
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("blur", reset);
    document.addEventListener("mouseleave", reset);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      video.removeEventListener("loadedmetadata", centre);
      video.removeEventListener("seeked", onSeeked);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("blur", reset);
      document.removeEventListener("mouseleave", reset);
    };
  }, [ref]);
}

function CopyIcon({ copied }) {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
      {copied ? (
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
  const videoRef = React.useRef(null);
  const { displayed, done } = useTyped(HERO_LINE);
  const [pillsOn, setPillsOn] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  useScrubVideo(videoRef);
  useIsoLayoutEffect(() => {
    if (isStill()) {
      setPillsOn(true);
      return;
    }
    const timeout = window.setTimeout(() => setPillsOn(true), 400);
    return () => window.clearTimeout(timeout);
  }, []);
  React.useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timeout);
  }, [copied]);
  const copyEmail = async () => {
    try {
      await navigator.clipboard.writeText(site.email);
      setCopied(true);
    } catch {
      window.location.href = `mailto:${site.email}`;
    }
  };
  return (
    <section className="scrub" id="top">
      <video
        ref={videoRef}
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
        <a className="scrub__news" href={HERO_NEWS.href}>
          <span className="scrub__news-tag">New</span>
          <span>{HERO_NEWS.label}</span>
          <span aria-hidden="true">→</span>
        </a>
        <p className="scrub__label">
          {HERO_GREETING}
          <br />
          {HERO_SYSTEM}
        </p>
        <h1 className="scrub__title">{HERO_TITLE}</h1>
        <p className="scrub__type">
          <span className="u-sr">{HERO_LINE}</span>
          <span aria-hidden="true">
            {displayed}
            {!done && <span className="scrub__caret" />}
          </span>
        </p>
        <div className={`scrub__pills${pillsOn ? " is-on" : ""}`} data-hero-cta>
          {heroPills.map((pill) => (
            <a className="pill" href={pill.href} key={pill.href}>
              {pill.label}
            </a>
          ))}
          <button className="pill pill--out" type="button" onClick={copyEmail}>
            <span>
              {"Reach us: "}
              <span className="pill__mail">{site.email}</span>
            </span>
            <CopyIcon copied={copied} />
            <span className="u-sr" aria-live="polite">
              {copied ? "Address copied" : "Copy address"}
            </span>
          </button>
        </div>
      </div>
    </section>
  );
}

const features = [
  {
    id: "f1",
    title: "Bounce to contact, in the next permitted window",
    body: "A mandate fails at 9:04. The bounce reaches PayInt as an event, the case opens straight away, and a written notice with a pay link goes out in the next permitted window. Where you switch calling on, a voice agent follows under the same rules.",
    notes: ["Real-time bounce events", "Written notice first", "Retry timed to payday"],
  },
  {
    id: "f2",
    title: "Every promise in writing, before the call ends",
    body: "The promise is captured on the call and sent in writing while the customer is still on the line, with a pay link they can use straight away and a reminder on the day it falls due.",
    notes: ["In-call pay link", "Written confirmation", "Revision history kept"],
  },
  {
    id: "f3",
    title: "The engine decides. The model explains.",
    body: "The next best action comes from a rule-based engine that weighs ten options in money against doing nothing. No language model takes part in that choice. One can explain it afterwards, in plain words, using only numbers from the record.",
    notes: ["Ten actions scored", "No LLM in the decision", "Every decision explained"],
  },
  {
    id: "f4",
    title: "Consent and calling hours are hard gates",
    body: "Do-not-contact status, calling hours, consent and contact caps are checked before anything is dialled, and the calling window is checked again at the dial. Settlements always go to a person, and voice agents have no waiver tool at all.",
    notes: ["DND and calling hours", "One daily cap, every channel", "Settlements go to a person"],
  },
  {
    id: "f5",
    title: "Every conversation scored, not sampled",
    body: "Not a two per cent sample read next week. Every Voice Studio call is graded after it ends: rules settle what they can, small models running inside your deployment take the easy judgement calls, and an AI judge reads a masked transcript for the rest. Every score shows what decided it and the turns it relied on.",
    notes: ["Every conversation", "Evidence per score", "Masked before judging"],
  },
  {
    id: "f6",
    title: "Compose the agent in Voice Studio.",
    body: "Workflows, tools and knowledge, drafted in the studio or from Claude over MCP. A person still publishes, and the release gate will not pass an agent that can reach account data before it has checked who it is talking to.",
    notes: ["Voice and WhatsApp", "MCP drafts only", "Identity-gated tools"],
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
            Bounce to contact, promise to paper, decision to action. Worked by Voice Studio agents,
            governed by rules the agents cannot talk their way past.
          </p>
        </div>
        <div className="features">
          {features.map((feature, index) => (
            <article
              className={`feature${index % 2 === 1 ? " feature--flip" : ""}`}
              key={feature.id}
            >
              <div className="feature__copy">
                <p className="feature__index rise" data-fx>
                  {String(index + 1).padStart(2, "0")}
                </p>
                <h3 className="rise" data-fx>
                  {feature.title}
                </h3>
                <p className="rise" data-fx>
                  {feature.body}
                </p>
                <ul className="feature__notes rise" data-fx>
                  {feature.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </div>
              <div className="feature__media rise" data-fx>
                <video
                  src={`/videos/${feature.id}.mp4`}
                  poster={`/videos/${feature.id}.jpg`}
                  muted
                  loop
                  playsInline
                  preload="none"
                  aria-hidden="true"
                />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Items listed per group on the home panel before "and N more". */
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
              <i>{moduleCount} modules.</i>
            </span>
            <span className="line">
              <i>One governed pipeline.</i>
            </span>
          </h2>
          <p className="platform__lede rise" data-fx>
            Voice, WhatsApp and the workspace your collectors already live in. Voice Studio to build
            the agents, a customer record that remembers everything, and an audit trail that can
            answer for all of it.
          </p>
        </div>
        <div className="platform__grid">
          {moduleGroups.map((group) => (
            <div className="pillar rise" data-fx key={group.name}>
              <h3 className="pillar__name">{group.name}</h3>
              <p className="pillar__desc">{group.note}</p>
              <ul className="pillar__list">
                {group.items.slice(0, PILLAR_PREVIEW).map(([name]) => (
                  <li key={name}>{name}</li>
                ))}
                {group.items.length > PILLAR_PREVIEW ? (
                  <li>
                    <a href={`/product/#${group.name.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
                      and {group.items.length - PILLAR_PREVIEW} more
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

// Properties of the code as it ships, not targets or a good month's figures.
const homeMetrics = [
  { to: 10, unit: "", k: "Actions weighed in money for every account, waiting included" },
  { to: 100, unit: "%", k: "Of conversations get a scorecard, not a sample" },
  {
    to: 2,
    unit: "",
    k: "Calling-window checks on every dial: when it is planned and when it is placed",
  },
  { to: 0, unit: "", k: "Language models inside the decision. One explains it afterwards" },
];

function HomeMetrics() {
  return (
    <section className="section">
      <div className="shell">
        <div className="section__head">
          <p className="eyebrow rise" data-fx>
            By design
          </p>
          <h2 className="display" data-split>
            <span className="line">
              <i>Four numbers that are</i>
            </span>
            <span className="line">
              <i>properties, not targets.</i>
            </span>
          </h2>
          <p className="lede rise" data-fx>
            Each one describes how the platform behaves today, in code. None of them is a figure
            from a good month.
          </p>
        </div>
        <div className="metrics">
          {homeMetrics.map((metric) => (
            <div className="metric rise" data-fx key={metric.k}>
              <p className="metric__n">
                <span data-count={metric.to}>{metric.to}</span>
                {metric.unit ? <span className="metric__unit">{metric.unit}</span> : null}
              </p>
              <p className="metric__k">{metric.k}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const trustItems = [
  {
    h: "It runs where you choose",
    p: "Containers on your own servers or cloud account. Post-call intelligence runs on local models with no internet access. Live speech and language services run on your keys, in your region, or on self-hosted models where a deployment needs it.",
  },
  {
    h: "Every decision is answerable",
    p: "Each action records the rules in force, every rule it consulted, the options it beat and why. When the auditor asks why this customer was called at that hour, there is one answer.",
  },
  {
    h: "Insurance, in early access",
    p: "Mandate recovery, one contact budget per customer and suitability-gated offers already carry over. Renewal and lapse workflows are being built with design partners.",
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
          {trustItems.map((item) => (
            <div className="trust__item rise" data-fx key={item.h}>
              <h3>{item.h}</h3>
              <p>{item.p}</p>
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
          Thirty minutes, your book, your rules. We will run one account end to end.
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
