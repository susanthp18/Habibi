import React from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

const HELIX_W = 720,
  HELIX_H = 760,
  HELIX_SPAN = 1500,
  HELIX_AMP = 118,
  HELIX_TILT = -42,
  HELIX_STEPS = 190;
export function Helix({ count: f = 30, turns: a = 4.6, scrub: r = 7 }) {
  const l = React.useRef(null),
    s = React.useMemo(() => {
      const d = (a * Math.PI * 2) / (f - 1),
        m = HELIX_SPAN / (f - 1),
        g = (HELIX_W - HELIX_SPAN) / 2,
        y = (b, S, x) => {
          const E = b * d + S + (x ? Math.PI : 0);
          return {
            x: g + b * m,
            y: HELIX_H / 2 + HELIX_AMP * Math.sin(E),
            d: Math.cos(E),
            s: Math.sin(E),
          };
        };
      return {
        at: y,
        path: (b, S, x) => {
          let E = "";
          for (let w = 0; w <= HELIX_STEPS; w++) {
            const O = (w / HELIX_STEPS) * (f - 1),
              { x: H, y: U } = y(O, b, S);
            E += `${w ? "L" : "M"}${H.toFixed(1)},${(U + x).toFixed(1)}`;
          }
          return E;
        },
        indices: Array.from(
          {
            length: f,
          },
          (b, S) => S,
        ),
      };
    }, [f, a]);
  React.useEffect(() => {
    const d = l.current;
    if (
      !d ||
      location.search.includes("still") ||
      matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const m = d.querySelectorAll("[data-node]"),
      g = d.querySelectorAll("[data-rung]"),
      y = d.querySelectorAll("[data-ribbon]");
    let v = 0,
      b = 0;
    const S = (w) => {
        (y.forEach((O) => {
          const H = O.dataset.ribbon === "b",
            U = Number(O.dataset.offset ?? 0);
          O.setAttribute("d", s.path(w, H, U));
        }),
          m.forEach((O) => {
            const H = Number(O.dataset.i),
              U = O.dataset.node === "b",
              { x: G, y: q, d: Q } = s.at(H, w, U),
              W = (Q + 1) / 2;
            (O.setAttribute("cx", G.toFixed(1)),
              O.setAttribute("cy", q.toFixed(1)),
              O.setAttribute("r", (6 + W * 6.5).toFixed(2)),
              O.setAttribute("opacity", (0.2 + W * 0.8).toFixed(3)));
          }),
          g.forEach((O) => {
            const H = Number(O.dataset.i),
              U = s.at(H, w, false),
              G = s.at(H, w, true);
            (O.setAttribute("transform", `translate(${U.x.toFixed(1)} 0)`),
              O.querySelectorAll("line").forEach((q) => {
                (q.setAttribute("y1", U.y.toFixed(1)), q.setAttribute("y2", G.y.toFixed(1)));
              }),
              O.setAttribute("opacity", (H % 2 ? 0 : 0.14 + Math.abs(U.s) * 0.34).toFixed(3)));
          }));
      },
      x = (w, O) => {
        ((v += O * 42e-5), S(v + b));
      };
    gsap.ticker.add(x);
    const E = ScrollTrigger.create({
      trigger: d,
      start: "top bottom",
      end: "bottom top",
      onUpdate: (w) => {
        b = w.progress * r;
      },
    });
    return () => {
      (gsap.ticker.remove(x), E.kill());
    };
  }, [s, r]);
  const c = 0;
  return (
    <svg
      ref={l}
      className="helix"
      viewBox={`0 0 ${HELIX_W} ${HELIX_H}`}
      role="img"
      aria-label="Two curves running in parallel: the probability of cure with an intervention, and without one. The rungs mark the accounts where they differ."
    >
      <g transform={`rotate(${HELIX_TILT} ${HELIX_W / 2} ${HELIX_H / 2})`}>
        {s.indices.map((d) => {
          const m = s.at(d, c, false),
            g = s.at(d, c, true);
          return (
            <g
              className="helix__rung"
              data-rung
              data-i={d}
              transform={`translate(${m.x.toFixed(1)} 0)`}
              opacity={(d % 2 ? 0 : 0.14 + Math.abs(m.s) * 0.34).toFixed(3)}
              key={`r${d}`}
            >
              <line x1={-2.2} x2={-2.2} y1={m.y.toFixed(1)} y2={g.y.toFixed(1)} />
              <line x1={2.2} x2={2.2} y1={m.y.toFixed(1)} y2={g.y.toFixed(1)} />
            </g>
          );
        })}
        {["a", "b"].map((d) =>
          [-3, 3].map((m) => (
            <path
              className={`helix__ribbon helix__ribbon--${d}`}
              data-ribbon={d}
              data-offset={m}
              d={s.path(c, d === "b", m)}
              key={`${d}${m}`}
            />
          )),
        )}
        {["a", "b"].map((d) =>
          s.indices.map((m) => {
            const { x: g, y, d: v } = s.at(m, c, d === "b"),
              b = (v + 1) / 2;
            return (
              <circle
                className={`helix__node helix__node--${d}`}
                data-node={d}
                data-i={m}
                cx={g.toFixed(1)}
                cy={y.toFixed(1)}
                r={(6 + b * 6.5).toFixed(2)}
                opacity={(0.2 + b * 0.8).toFixed(3)}
                key={`${d}${m}`}
              />
            );
          }),
        )}
      </g>
    </svg>
  );
}
