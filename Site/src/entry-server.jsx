import React from "react";
import { renderToString } from "react-dom/server";
import { App } from "./App";

export { routes } from "./routes";
export { site } from "./site";
export { faqs } from "./data/faqs";

export function render(path) {
  return renderToString(
    <React.StrictMode>
      <App path={path} />
    </React.StrictMode>,
  );
}
