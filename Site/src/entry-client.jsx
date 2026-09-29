import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { routeFor } from "./routes";
import "./styles.css";

const initialPath = location.pathname;
if (location.search.includes("still")) document.documentElement.classList.add("is-still");

const rootEl = document.getElementById("root");
const appTree = (
  <React.StrictMode>
    <App path={initialPath} />
  </React.StrictMode>
);
if (rootEl.firstElementChild) ReactDOM.hydrateRoot(rootEl, appTree);
else ReactDOM.createRoot(rootEl).render(appTree);

// `vite dev` serves the bare template; give it the route's title.
if (!document.title) {
  const route = routeFor(initialPath);
  document.title = route.title;
  const meta = document.createElement("meta");
  meta.name = "description";
  meta.content = route.description;
  document.head.appendChild(meta);
}
