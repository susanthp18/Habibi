import { createFileRoute } from "@tanstack/react-router";
import { LoginScreen } from "@/components/auth/LoginScreen";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Sign in — PayInt" },
      {
        name: "description",
        content:
          "Sign in to PayInt with your BigTapp Microsoft account. Autonomous Payment Intelligence for collections.",
      },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  return <LoginScreen />;
}
