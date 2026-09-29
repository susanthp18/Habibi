import React from "react";
import { CorpMark, Mark } from "./Brand";
import { navRoutes, routes } from "../routes";

export function Header({ path }) {
  const [stuck, setStuck] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const onScroll = () => setStuck(window.scrollY > 40);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = overflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const sheetRoutes = routes.filter((route) => route.nav || route.path === "/");
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className={`nav${stuck ? " nav--stuck" : ""}`}>
        <div className="nav__in">
          <a className="nav__brand" href="/" aria-label="PayInt home">
            <Mark />
            <span className="nav__word">PayInt</span>
            <span className="nav__star" aria-hidden="true">
              ✳︎
            </span>
          </a>
          <nav className="nav__links" aria-label="Primary">
            {navRoutes.map((route) => (
              <a
                href={route.path}
                className={path === route.path ? "is-here" : undefined}
                aria-current={path === route.path ? "page" : undefined}
                key={route.path}
              >
                {route.nav}
              </a>
            ))}
          </nav>
          <div className="nav__end">
            <a className="nav__signin" href="/login">
              Sign in
            </a>
            <CorpMark className="nav__corp" size={64} />
            <button
              className={`nav__burger${open ? " is-open" : ""}`}
              type="button"
              aria-label={open ? "Close menu" : "Open menu"}
              aria-expanded={open}
              aria-controls="site-menu"
              onClick={() => setOpen((value) => !value)}
            >
              <span />
              <span />
              <span />
            </button>
          </div>
        </div>
      </header>
      <div
        className={`sheet${open ? " is-open" : ""}`}
        id="site-menu"
        aria-hidden={!open}
        inert={open ? undefined : true}
        onClick={() => setOpen(false)}
      >
        <nav className="sheet__links" aria-label="Primary, mobile">
          {sheetRoutes.map((route) => (
            <a
              href={route.path}
              aria-current={path === route.path ? "page" : undefined}
              key={route.path}
            >
              {route.nav ?? "Home"}
            </a>
          ))}
          <a href="/demo/">Book a walkthrough</a>
          <a className="sheet__cta" href="/login">
            Sign in
          </a>
        </nav>
      </div>
    </>
  );
}
