import React from "react";
import { CorpMark, Mark } from "./Brand";
import { navRoutes, routes } from "../routes";

export function Header({ path: f }) {
  const [a, r] = React.useState(false),
    [l, s] = React.useState(false),
    [c, d] = React.useState(false);
  (React.useEffect(() => {
    const g = () => r(window.scrollY > 40);
    return (
      g(),
      window.addEventListener("scroll", g, {
        passive: true,
      }),
      () => window.removeEventListener("scroll", g)
    );
  }, []),
    React.useEffect(() => {
      const g = document.querySelector("[data-hero-cta]");
      if (!g) {
        s(true);
        return;
      }
      const y = new IntersectionObserver(([v]) => s(!v.isIntersecting), {
        threshold: 0,
      });
      return (y.observe(g), () => y.disconnect());
    }, []),
    React.useEffect(() => {
      if (!c) return;
      const g = (v) => {
          v.key === "Escape" && d(false);
        },
        y = document.body.style.overflow;
      return (
        (document.body.style.overflow = "hidden"),
        window.addEventListener("keydown", g),
        () => {
          ((document.body.style.overflow = y), window.removeEventListener("keydown", g));
        }
      );
    }, [c]));
  const m = routes.filter((g) => g.nav || g.path === "/");
  return (
    <>
      <header className={`nav${a ? " nav--stuck" : ""}`}>
        <div className="nav__in">
          <a className="nav__brand" href="/" aria-label="PayInt home">
            <Mark />
            <span className="nav__word">PayInt</span>
            <span className="nav__star" aria-hidden="true">
              ✳︎
            </span>
          </a>
          <nav className="nav__links" aria-label="Primary">
            {navRoutes.map((g) => (
              <a
                href={g.path}
                className={f === g.path ? "is-here" : void 0}
                aria-current={f === g.path ? "page" : void 0}
                key={g.path}
              >
                {g.nav}
              </a>
            ))}
          </nav>
          <div className="nav__end">
            <a
              className={`btn btn--primary nav__cta${l ? " nav__cta--on" : ""}`}
              href="/login"
              aria-hidden={!l}
              tabIndex={l ? void 0 : -1}
            >
              Sign in
            </a>
            <CorpMark className="nav__corp" size={64} />
            <button
              className={`nav__burger${c ? " is-open" : ""}`}
              type="button"
              aria-label={c ? "Close menu" : "Open menu"}
              aria-expanded={c}
              onClick={() => d((g) => !g)}
            >
              <span />
              <span />
              <span />
            </button>
          </div>
        </div>
      </header>
      <div className={`sheet${c ? " is-open" : ""}`} aria-hidden={!c} onClick={() => d(false)}>
        <nav className="sheet__links" aria-label="Primary, mobile">
          {m.map((g) => (
            <a href={g.path} aria-current={f === g.path ? "page" : void 0} key={g.path}>
              {g.nav ?? "Home"}
            </a>
          ))}
          <a className="sheet__cta" href="/login">
            Sign in
          </a>
        </nav>
      </div>
    </>
  );
}
