import React from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

// index.html puts `fx` on <html> before first paint, which is what hides the
// reveal targets (.rise, .line > i) until they animate in. It also takes the
// class off again if this script has not arrived within a few seconds, so a
// failed or blocked bundle leaves a readable page rather than a blank one.
if (typeof window !== "undefined") window.__payintFx = true;

/** Scroll reveals, stat counters and in-view video playback for the whole site. */
export function useSiteFx() {
  React.useEffect(() => {
    const still =
      location.search.includes("still") || matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ctx = gsap.context(() => {
      const videos = new IntersectionObserver(
        (entries) =>
          entries.forEach(({ target, isIntersecting }) => {
            if (isIntersecting) target.play().catch(() => {});
            else target.pause();
          }),
        { threshold: 0.15 },
      );
      document
        .querySelectorAll("video:not(.scrub__video)")
        .forEach((video) => videos.observe(video));

      const rails = gsap.utils.toArray("[data-rail]");
      if (still) {
        gsap.set(".line > i", { y: 0 });
        gsap.set(".rise", { opacity: 1, y: 0 });
        rails.forEach((rail) => {
          rail.style.setProperty("--p", "1");
          rail.querySelectorAll(":scope > li").forEach((step) => step.classList.add("is-lit"));
        });
        return () => videos.disconnect();
      }
      // Step rails fill with the scroll, and each step lights as the line reaches it.
      rails.forEach((rail) => {
        const steps = rail.querySelectorAll(":scope > li");
        const paint = (self) => {
          rail.style.setProperty("--p", self.progress.toFixed(3));
          const line = window.innerHeight * 0.62;
          steps.forEach((step) =>
            step.classList.toggle("is-lit", step.getBoundingClientRect().top + 24 < line),
          );
        };
        ScrollTrigger.create({
          trigger: rail,
          start: "top 62%",
          end: "bottom 62%",
          onUpdate: paint,
          onRefresh: paint,
        });
      });

      if (document.querySelector("[data-hero-fx]")) {
        gsap.to("[data-hero-fx]", {
          opacity: 1,
          y: 0,
          duration: 0.95,
          stagger: 0.07,
          ease: "power3.out",
          delay: 0.15,
        });
      }
      gsap.utils.toArray("[data-split]").forEach((heading) => {
        gsap.to(heading.querySelectorAll(".line > i"), {
          y: 0,
          duration: 1.2,
          ease: "power3.out",
          stagger: 0.09,
          scrollTrigger: { trigger: heading, start: "top 86%" },
        });
      });
      gsap.utils.toArray("[data-fx]").forEach((el) => {
        gsap.to(el, {
          opacity: 1,
          y: 0,
          duration: 0.9,
          ease: "power3.out",
          scrollTrigger: { trigger: el, start: "top 92%" },
        });
      });
      // Counters are prerendered at their real value (what crawlers, link
      // previews and no-JS readers get). Only one that is still below the
      // fold is wound back to 0, so the count-up never flashes on screen.
      document.querySelectorAll("[data-count]").forEach((el) => {
        if (el.getBoundingClientRect().top < window.innerHeight) return;
        const target = Number(el.dataset.count ?? 0);
        const counter = { value: 0 };
        el.textContent = "0";
        gsap.to(counter, {
          value: target,
          duration: 1.5,
          ease: "power2.out",
          onUpdate: () => {
            el.textContent = String(Math.round(counter.value));
          },
          scrollTrigger: { trigger: el, start: "top 90%" },
        });
      });
      return () => videos.disconnect();
    });
    return () => ctx.revert();
  }, []);
}
