import { createFileRoute } from "@tanstack/react-router";
import { Check, Moon, Sun } from "lucide-react";
import { can, useMe } from "@/api/me";
import { Button } from "@/components/ui/button";
import { SwitchesSection } from "@/components/settings/SwitchesSection";
import { TestCallSection } from "@/components/settings/TestCallSection";
import { TestNumbersSection } from "@/components/settings/TestNumbersSection";
import { setTheme, useTheme } from "@/lib/theme";

export const Route = createFileRoute("/_app/settings")({
  head: () => ({
    meta: [
      { title: "Settings — PayInt" },
      {
        name: "description",
        content: "Appearance, automation switches, test numbers and test calls.",
      },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const theme = useTheme();
  const me = useMe();
  const isAdmin = can(me.data, "perm-admin-write");
  const canCall = can(me.data, "perm-voice-operate");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border bg-surface px-400 py-200">
        <h1 className="heading-medium font-semibold">Settings</h1>
        <p className="text-body-small text-text-subtle">
          Appearance for this browser. Admins also control what the platform may do on its own and
          which handsets test calls may ring. People and invites are in Roles &amp; access.
        </p>
      </header>
      <div className="min-h-0 flex-1 space-y-400 overflow-auto p-400">
        <section>
          <h2 className="text-body font-semibold">Appearance</h2>
          <p className="mb-200 mt-025 text-body-small text-text-subtle">
            Light and dark follow the same tokens as the rest of the console. Saved in this browser.
          </p>
          <div className="flex flex-wrap gap-100">
            <Button
              type="button"
              variant={theme === "light" ? "primary" : "default"}
              onClick={() => setTheme("light")}
            >
              <Sun className="h-4 w-4" />
              Light
              {theme === "light" ? <Check className="h-4 w-4" /> : null}
            </Button>
            <Button
              type="button"
              variant={theme === "dark" ? "primary" : "default"}
              onClick={() => setTheme("dark")}
            >
              <Moon className="h-4 w-4" />
              Dark
              {theme === "dark" ? <Check className="h-4 w-4" /> : null}
            </Button>
          </div>
        </section>

        {isAdmin ? (
          <>
            <SwitchesSection />
            <TestNumbersSection />
          </>
        ) : null}
        {canCall ? <TestCallSection /> : null}
      </div>
    </div>
  );
}
