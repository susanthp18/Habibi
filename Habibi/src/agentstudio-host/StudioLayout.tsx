/**
 * AgentStudio inside Habibi's shell: the engine UI's app-wide providers
 * (health/TURN config, org model config, telephony warnings, onboarding
 * hints) around the page, in a scroll container of its own (the shell's main
 * area does not scroll).
 */
import { Outlet } from "@tanstack/react-router";

import { client } from "@/agentstudio/client/client.gen";
import { OnboardingProvider } from "@/agentstudio/context/OnboardingContext";
import { OrgConfigProvider } from "@/agentstudio/context/OrgConfigContext";
import { TelephonyConfigWarningsProvider } from "@/agentstudio/context/TelephonyConfigWarningsContext";

import { signStudioClient } from "./api-client";
import { AppConfigProvider } from "./app-config";
import "./studio.css";

// Before any screen mounts: every engine request is signed by the app.
signStudioClient(client);

export function StudioLayout() {
  return (
    <AppConfigProvider>
      <OrgConfigProvider>
        <TelephonyConfigWarningsProvider>
          <OnboardingProvider>
            {/*
              `relative` is load-bearing. Radix gives a Switch/Checkbox a hidden
              <input style="position:absolute"> with no offsets; every ancestor
              up to the shell is statically positioned, so its containing block
              was the document itself and `overflow-hidden` on the shell could
              not clip it. One switch low on a long page stretched the document
              by its own offset, so the whole app scrolled up and left a blank
              band below it. Positioning this scroller adopts those inputs.
            */}
            <div className="agentstudio relative h-full overflow-auto">
              <Outlet />
            </div>
          </OnboardingProvider>
        </TelephonyConfigWarningsProvider>
      </OrgConfigProvider>
    </AppConfigProvider>
  );
}
