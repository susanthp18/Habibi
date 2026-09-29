import React from "react";
import { site } from "../site";

export function CorpMark({ className: f = "corp", size: a = 36 }) {
  return (
    <a
      className={f}
      href={site.companyUrl}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${site.company} home`}
    >
      <img src="/brand/bigtapp.png?v=5" alt="" width={a} height={a} />
    </a>
  );
}
const MARK_W = 75,
  MARK_H = 52;
export function Mark({ size: f = 26, animated: a = true }) {
  const r = Math.round((f * MARK_W) / MARK_H),
    l = f / MARK_H;
  return (
    <span
      className={`eq-mark${a ? " eq-mark--live" : ""}`}
      style={{
        width: r,
        height: f,
      }}
      role="img"
      aria-label="PayInt"
    >
      <span
        className="eq-mark__stage"
        style={{
          transform: `scale(${l})`,
        }}
      >
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__bar" />
        <span className="eq-mark__ball" />
      </span>
    </span>
  );
}
