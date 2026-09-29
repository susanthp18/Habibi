import React from "react";

// An illustrative live call as a supervisor sees it on Floor command: the agent
// talking, the transcript with account digits masked, and the three controls.
const lines = [
  ["Agent", "Thanks for confirming. I can see an instalment of ₹4,850 that bounced on the 4th."],
  ["Customer", "My salary comes in on the 7th. Can I pay then?"],
  ["Agent", "Yes. I'll send a pay link on WhatsApp for the 7th, ending •••• 2291."],
];

export function LiveCall() {
  return (
    <figure
      className="livecall rise"
      data-fx
      aria-label="An example live call on Floor command, with listen, whisper and take over controls"
    >
      <div className="livecall__head">
        <span className="livecall__dot" aria-hidden="true" />
        <span className="livecall__title">Live · Voice agent · Collections, Hindi and English</span>
        <span className="livecall__time">02:14</span>
      </div>
      <div className="livecall__wave" aria-hidden="true">
        {Array.from({ length: 28 }, (_, i) => (
          <span key={i} style={{ "--i": i, "--h": `${22 + ((i * 37) % 70)}%` }} />
        ))}
      </div>
      <ol className="livecall__lines">
        {lines.map(([who, said], i) => (
          <li key={i} className={who === "Agent" ? "is-agent" : undefined}>
            <span className="livecall__who">{who}</span>
            <span>{said}</span>
          </li>
        ))}
      </ol>
      <div className="livecall__controls" aria-hidden="true">
        <span className="is-on">Listening</span>
        <span>Whisper</span>
        <span>Take over</span>
      </div>
      <figcaption className="livecall__note">
        Masked for anyone without access to raw personal data.
      </figcaption>
    </figure>
  );
}
