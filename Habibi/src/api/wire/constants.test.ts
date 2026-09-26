// The vocabularies the TypeScript narrows on are the backend's. constants.json
// is generated from their Python owners (backend/scripts/gen_wire_schemas.py)
// and kept current by backend/tests/test_wire_schemas_current.py; this pins
// the hand-written `as const` lists to it, so a status that grows on one side
// cannot stay a missing option or a toneless lozenge on the other.
import { describe, expect, it } from "vitest";

import { SENDERS } from "@/api/types/inbox";
import {
  PROMISE_REVISION_REASONS,
  PROMISE_STATUSES,
  REMINDER_STATUSES,
} from "@/api/types/promises";
import constants from "./constants.json";

describe("wire constants", () => {
  it("promise and reminder statuses are the columns'", () => {
    expect([...PROMISE_STATUSES]).toEqual(constants.promiseStatuses);
    expect([...REMINDER_STATUSES]).toEqual(constants.reminderStatuses);
    expect([...PROMISE_REVISION_REASONS]).toEqual(constants.promiseRevisionReasons);
  });
  it("senders are the column's", () => {
    expect([...SENDERS]).toEqual(constants.senders);
  });
});
