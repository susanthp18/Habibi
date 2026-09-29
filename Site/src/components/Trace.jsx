import React from "react";

// An illustrative decision record, drawn the way Decision intelligence shows one:
// every option either scored in money or blocked before scoring, with the reason.
const options = [
  { action: "WhatsApp with a pay link", value: 412, state: "picked" },
  { action: "SMS with a pay link", value: 301, state: "scored" },
  { action: "Voice agent", value: 24, state: "scored" },
  { action: "Wait", value: 0, state: "scored" },
  { action: "Agent call", reason: "Outside calling hours", state: "blocked" },
  { action: "Field visit", reason: "Under 31 days past due", state: "blocked" },
];
const top = Math.max(...options.map((option) => option.value ?? 0));
const rupees = (value) => `₹${value.toLocaleString("en-IN")}`;

export function Trace() {
  const ref = React.useRef(null);
  const [on, setOn] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setOn(true);
          observer.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <figure
      ref={ref}
      className={`trace rise${on ? " is-on" : ""}`}
      data-fx
      aria-label="An example decision record: six options, four scored in money and two blocked before scoring"
    >
      <div className="trace__head">
        <p className="trace__title">Why the engine decided this</p>
        <span className="trace__tag">Example</span>
      </div>
      <p className="trace__why">
        Trigger: EMI bounce, insufficient funds · Bank feed 2h old · Rules v14
      </p>
      <ol className="trace__rows">
        {options.map((option) => (
          <li className={`trace__row trace__row--${option.state}`} key={option.action}>
            <span className="trace__action">{option.action}</span>
            {option.state === "blocked" ? (
              <span className="trace__blocked">Blocked before scoring · {option.reason}</span>
            ) : (
              <span className="trace__score">
                <span className="trace__bar" aria-hidden="true">
                  <span style={{ "--w": `${Math.max(2, (option.value / top) * 100)}%` }} />
                </span>
                <span className="trace__value">{rupees(option.value)}</span>
              </span>
            )}
          </li>
        ))}
      </ol>
      <figcaption className="trace__foot">
        <span>
          Picked by <strong>₹111</strong> over the runner-up
        </span>
        <span>
          P(reach): learned, 18 of 64 in 90 days · P(pay | reach): this borrower's history
        </span>
      </figcaption>
    </figure>
  );
}
