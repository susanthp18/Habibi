import React from "react";
import { Footer } from "./components/Footer";
import { Header } from "./components/Header";
import { useSiteFx } from "./fx";
import { routeFor } from "./routes";

export function App({ path }) {
  const route = routeFor(path);
  const Page = route.component;
  useSiteFx();
  return (
    <>
      <Header path={route.path} />
      <main id="main" tabIndex={-1}>
        <Page />
      </main>
      <Footer />
    </>
  );
}
