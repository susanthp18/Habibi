/**
 * Loaded only by suites that opt into jsdom. Pure-function tests stay on
 * `environment: "node"` and must not import this file.
 *
 * Radix (dropdown, select, slider) calls pointer-capture and scroll APIs
 * that jsdom leaves unimplemented. Stub the holes; do not polyfill APIs
 * jsdom already provides.
 *
 * `@testing-library/react` only auto-cleans when `afterEach` is global.
 * This repo does not set `globals: true`, so we have to hook it ourselves —
 * otherwise a portaled dropdown from test N is still in the document for N+1.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

const proto = HTMLElement.prototype;
if (typeof proto.hasPointerCapture !== "function") {
  proto.hasPointerCapture = () => false;
}
if (typeof proto.setPointerCapture !== "function") {
  proto.setPointerCapture = () => {};
}
if (typeof proto.releasePointerCapture !== "function") {
  proto.releasePointerCapture = () => {};
}
if (typeof proto.scrollIntoView !== "function") {
  proto.scrollIntoView = () => {};
}
if (typeof proto.scrollTo !== "function") {
  proto.scrollTo = () => {};
}

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
