import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/telephony-configurations/page";

export const Route = createFileRoute("/_app/studio/telephony-configurations/")({
  head: () => ({ meta: [{ title: "Telephony · Voice Studio — PayInt" }] }),
  component: Page,
});
