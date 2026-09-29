import React from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);
export function useSiteFx() {
  React.useEffect(() => {
    const f = location.search.includes("still"),
      a = matchMedia("(prefers-reduced-motion: reduce)").matches,
      r = gsap.context(() => {
        const l = new IntersectionObserver(
          (s) =>
            s.forEach((c) => {
              const d = c.target;
              c.isIntersecting ? d.play().catch(() => {}) : d.pause();
            }),
          {
            threshold: 0.15,
          },
        );
        return (
          document.querySelectorAll("video:not(.scrub__video)").forEach((s) => l.observe(s)),
          f || a
            ? (gsap.set(".line > i", {
                y: 0,
              }),
              gsap.set(".rise", {
                opacity: 1,
                y: 0,
              }),
              document
                .querySelectorAll("[data-count]")
                .forEach((s) => (s.textContent = s.dataset.count ?? "0")),
              () => l.disconnect())
            : (gsap.to("[data-hero-fx]", {
                opacity: 1,
                y: 0,
                duration: 0.95,
                stagger: 0.07,
                ease: "power3.out",
                delay: 0.15,
              }),
              gsap.utils.toArray("[data-split]").forEach((s) => {
                gsap.to(s.querySelectorAll(".line > i"), {
                  y: 0,
                  duration: 1.2,
                  ease: "power3.out",
                  stagger: 0.09,
                  scrollTrigger: {
                    trigger: s,
                    start: "top 86%",
                  },
                });
              }),
              gsap.utils.toArray("[data-fx]").forEach((s) => {
                gsap.to(s, {
                  opacity: 1,
                  y: 0,
                  duration: 0.9,
                  ease: "power3.out",
                  scrollTrigger: {
                    trigger: s,
                    start: "top 92%",
                  },
                });
              }),
              document.querySelectorAll("[data-count]").forEach((s) => {
                const c = Number(s.dataset.count ?? 0),
                  d = {
                    v: 0,
                  };
                gsap.to(d, {
                  v: c,
                  duration: 1.5,
                  ease: "power2.out",
                  onUpdate: () => (s.textContent = String(Math.round(d.v))),
                  scrollTrigger: {
                    trigger: s,
                    start: "top 90%",
                  },
                });
              }),
              () => {
                l.disconnect();
              })
        );
      });
    return () => r.revert();
  }, []);
}
