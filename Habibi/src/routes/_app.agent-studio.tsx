import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/_app/agent-studio")({
  component: () => <Outlet />,
  head: () => ({
    meta: [
      { title: "Agent studio — BigBound AI" },
      {
        name: "description",
        content: "Fleet console for first-party agent cards. Publish is a compiler.",
      },
    ],
  }),
});
