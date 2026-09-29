import React from "react";

function Lines({ lines: f }) {
  return (
    <>
      {f.map((a, r) => (
        <span className="line" key={r}>
          <i>{a}</i>
        </span>
      ))}
    </>
  );
}
export function PageHero({
  eyebrow: f,
  title: a,
  lede: r,
  primary: l = {
    label: "Book a walkthrough",
    href: "/demo/",
  },
  secondary: s,
  proof: c,
}) {
  return (
    <section className="phero">
      <div className="shell">
        <p className="eyebrow rise" data-hero-fx>
          {f}
        </p>
        <h1 className="display phero__h1" data-split>
          <Lines lines={a} />
        </h1>
        <div className="phero__body">
          <p className="lede rise" data-hero-fx>
            {r}
          </p>
          <div className="phero__cta rise" data-hero-fx data-hero-cta>
            <a className="btn btn--primary" href={l.href}>
              {l.label}
            </a>
            {s ? (
              <a className="btn btn--quiet" href={s.href}>
                {s.label}
              </a>
            ) : null}
          </div>
        </div>
        {c != null && c.length ? (
          <div className="phero__proof rise" data-hero-fx>
            {c.map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
export function Section({ id: f, eyebrow: a, title: r, lede: l, children: s, wide: c }) {
  return (
    <section className="section" id={f}>
      <div className="shell">
        {a || r || l ? (
          <div className={`section__head${c ? " section__head--wide" : ""}`}>
            {a ? (
              <p className="eyebrow rise" data-fx>
                {a}
              </p>
            ) : null}
            {r ? (
              <h2 className="display" data-split>
                <Lines lines={r} />
              </h2>
            ) : null}
            {l ? (
              <p className="lede rise" data-fx>
                {l}
              </p>
            ) : null}
          </div>
        ) : null}
        {s}
      </div>
    </section>
  );
}
export function Rows({ items: f }) {
  return (
    <dl className="rows">
      {f.map(([a, r], l) => (
        <div className="rise" data-fx key={l}>
          <dt>{a}</dt>
          <dd>{r}</dd>
        </div>
      ))}
    </dl>
  );
}
export function Steps({ items: f }) {
  return (
    <ol className="steps">
      {f.map(([a, r], l) => (
        <li className="rise" data-fx key={l}>
          <span className="steps__n">{String(l + 1).padStart(2, "0")}</span>
          <div>
            <h3>{a}</h3>
            <p>{r}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
export function Cols({ items: f, of: a = 3 }) {
  return (
    <div className={`cols cols--${a}`}>
      {f.map(([r, l], s) => (
        <div className="rise" data-fx key={s}>
          <h3>{r}</h3>
          <p>{l}</p>
        </div>
      ))}
    </div>
  );
}
export function Panel({ eyebrow: f, title: a, lede: r, children: l }) {
  return (
    <section className="platform">
      <div className="platform__in">
        <div className="platform__head">
          {f ? (
            <p className="eyebrow rise" data-fx>
              {f}
            </p>
          ) : null}
          <h2 className="display" data-split>
            <Lines lines={a} />
          </h2>
          {r ? (
            <p className="platform__lede rise" data-fx>
              {r}
            </p>
          ) : null}
        </div>
        {l}
      </div>
    </section>
  );
}
export function Metrics({ items: f }) {
  return (
    <div className="metrics">
      {f.map((a) => (
        <div
          className={`metric rise${/[A-Za-z]{3,}/.test(a.n) ? " metric--word" : ""}`}
          data-fx
          key={a.k}
        >
          <p className="metric__n">{a.n}</p>
          <p className="metric__k">{a.k}</p>
          {a.note ? <p className="metric__note">{a.note}</p> : null}
        </div>
      ))}
    </div>
  );
}
export function Table({ head: f, rows: a, caption: r }) {
  return (
    <div className="tablewrap rise" data-fx>
      <table className="table">
        <thead>
          <tr>
            {f.map((l) => (
              <th scope="col" key={l}>
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {a.map((l, s) => (
            <tr key={s}>
              {l.map((c, d) =>
                d === 0 ? (
                  <th scope="row" key={d}>
                    {c}
                  </th>
                ) : (
                  <td key={d}>{c}</td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {r ? <p className="table__note">{r}</p> : null}
    </div>
  );
}
export function Pull({ children: f, by: a }) {
  return (
    <figure className="pull rise" data-fx>
      <blockquote>{f}</blockquote>
      {a ? <figcaption>{a}</figcaption> : null}
    </figure>
  );
}
export function Faq({ items: f }) {
  return (
    <div className="faq">
      {f.map(([a, r]) => (
        <details className="faq__item rise" data-fx key={a}>
          <summary>
            <h3>{a}</h3>
            <span className="faq__mark" aria-hidden="true" />
          </summary>
          <p>{r}</p>
        </details>
      ))}
    </div>
  );
}
export function Closing({
  title: f,
  lede: a,
  primary: r = {
    label: "Book a walkthrough",
    href: "/demo/",
  },
  secondary: l,
}) {
  return (
    <div className="shell">
      <section className="closing">
        <h2 className="display" data-split>
          <Lines lines={f} />
        </h2>
        <p className="lede rise" data-fx>
          {a}
        </p>
        <div className="closing__row rise" data-fx>
          <a className="btn btn--primary" href={r.href}>
            {r.label}
          </a>
          {l ? (
            <a className="btn btn--quiet" href={l.href}>
              {l.label}
            </a>
          ) : null}
        </div>
      </section>
    </div>
  );
}
export function More({ links: f }) {
  return (
    <div className="shell">
      <nav className="more" aria-label="Related pages">
        {f.map(([a, r, l]) => (
          <a className="more__item rise" data-fx href={a} key={a}>
            <span className="more__h">{r}</span>
            <span className="more__p">{l}</span>
          </a>
        ))}
      </nav>
    </div>
  );
}
