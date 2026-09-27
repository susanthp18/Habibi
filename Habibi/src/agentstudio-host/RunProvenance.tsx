/**
 * Host slot "@/host/RunProvenance" for the ported run page: which agent version
 * ran, which approved tools it called and how each one ended -- and, for a call
 * filed in PayInt, its compliance and QA with the recording as PayInt plays it.
 */
import type { ComponentProps } from "react";

import Provenance from "@/components/voice-studio/RunProvenance";
import { RunCallIntel } from "@/components/voice-studio/RunCallIntel";

type Props = ComponentProps<typeof Provenance> & { runId?: number };

export default function RunProvenance({ runId, ...props }: Props) {
  return (
    <>
      <Provenance {...props} />
      {runId != null && <RunCallIntel runId={runId} />}
    </>
  );
}
