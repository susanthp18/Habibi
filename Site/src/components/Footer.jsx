import React from "react";
import { CorpMark, Mark } from "./Brand";
import { routes, shortTitle } from "../routes";
import { site } from "../site";

const footGroups = ["Platform", "Industries", "Company"];
export function Footer() {
  return (
    <footer className="foot">
      <div className="shell foot__in">
        <div className="foot__brand">
          <a className="nav__brand" href="/" aria-label="PayInt home">
            <Mark />
            <span className="nav__word">PayInt</span>
          </a>
          <p>
            A collections and recovery operating system for banks, lenders, card issuers and
            insurers. Deployed inside your perimeter.
          </p>
          <a className="foot__mail" href={`mailto:${site.email}`}>
            {site.email}
          </a>
        </div>
        <div className="foot__cols">
          {footGroups.map((f) => (
            <div key={f}>
              <h2>{f}</h2>
              <ul>
                {routes
                  .filter((a) => a.foot === f)
                  .map((a) => (
                    <li key={a.path}>
                      <a href={a.path}>{a.label ?? a.nav ?? shortTitle(a.title)}</a>
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="shell foot__bar">
        <span className="foot__legal">
          <CorpMark className="foot__corp" size={40} />
          <span>
            {"© "}
            {new Date().getFullYear()} {site.company}. All rights reserved.
          </span>
        </span>
        <span>On-premise by default · No customer data leaves your perimeter</span>
      </div>
    </footer>
  );
}
