import { createFileRoute } from "@tanstack/react-router";

import Page from "@/agentstudio/app/telephony-configurations/[configId]/page";

export const Route = createFileRoute("/_app/studio/telephony-configurations/$configId")({
  head: () => ({ meta: [{ title: "Telephony configuration · Voice Studio — PayInt" }] }),
  component: Page,
});
