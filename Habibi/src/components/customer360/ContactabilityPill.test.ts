// -----------------------------------------------------------------------------
// contactabilityState is the fail-closed half of the pill: it decides what an
// operator is told when the verdict is missing, late, or expressed in a vocabulary
// this build has never seen. Only one of its branches may be green.
//
// It takes a duck-typed query object rather than a UseQueryResult, so none of
// this needs React, a QueryClientProvider, or a running backend.
// -----------------------------------------------------------------------------

import { describe, expect, it } from "vitest";

import type { ContactPolicy } from "@/api/contact-policy";
import type { Contact } from "@/data/customer360-seed";
import { contactabilityState } from "./ContactabilityPill";

const CONTACT: Contact = {
  phonePrimary: "+919000000001",
  email: "borrower@example.com",
  address: "Bengaluru",
  timezone: "Asia/Kolkata",
  language: "en",
  preferredWindow: "10:00–19:00 IST",
  dnd: false,
};

function policy(overrides: Partial<ContactPolicy> = {}): ContactPolicy {
  return {
    allowed: true,
    reason: null,
    touchCounted: false,
    outreachToday: 0,
    dailyCap: 3,
    coalesced: false,
    channel: "voice",
    purpose: "outreach",
    ...overrides,
  };
}

describe("when the verdict cannot be obtained", () => {
  it("renders the explicit unavailable state on a network failure", () => {
    const view = contactabilityState(CONTACT, { isPending: false, isError: true });
    expect(view.status).toBe("unknown");
    expect(view.tone).toBe("warning");
    expect(view.ok).toBe(false);
    expect(view.label).toBe("Contact policy unavailable");
  });

  it("renders the same state when the query settled with no data", () => {
    const view = contactabilityState(CONTACT, { isPending: false, isError: false });
    expect(view.status).toBe("unknown");
    expect(view.ok).toBe(false);
  });

  it("is neutral, not green, while the verdict is in flight", () => {
    const view = contactabilityState(CONTACT, { isPending: true, isError: false });
    expect(view.status).toBe("pending");
    expect(view.tone).toBe("neutral");
    expect(view.ok).toBe(false);
  });
});

describe("when the backend answers", () => {
  it("is the only green branch on an explicit allow", () => {
    const view = contactabilityState(CONTACT, {
      data: policy({ allowed: true }),
      isPending: false,
      isError: false,
    });
    expect(view.status).toBe("ok");
    expect(view.tone).toBe("success");
    expect(view.ok).toBe(true);
  });

  it("renders a known refusal with its own words", () => {
    const view = contactabilityState(CONTACT, {
      data: policy({ allowed: false, reason: "outside_calling_hours" }),
      isPending: false,
      isError: false,
    });
    expect(view.status).toBe("blocked");
    expect(view.tone).toBe("warning");
    expect(view.label).toBe("Outside calling hours");
    expect(view.ok).toBe(false);
  });

  it("renders an unknown future reason code as non-green", () => {
    // contact_policy.py may grow veto codes this build has never heard of. A
    // refusal it cannot name is still a refusal — it must not fall through to
    // "OK to contact".
    const view = contactabilityState(CONTACT, {
      data: policy({ allowed: false, reason: "reason_from_a_later_backend" }),
      isPending: false,
      isError: false,
    });
    expect(view.status).toBe("blocked");
    expect(view.tone).not.toBe("success");
    expect(view.ok).toBe(false);
    expect(view.sub).toContain("reason_from_a_later_backend");
  });

  it("renders a blocked verdict with a null reason as non-green", () => {
    const view = contactabilityState(CONTACT, {
      data: policy({ allowed: false, reason: null }),
      isPending: false,
      isError: false,
    });
    expect(view.tone).not.toBe("success");
    expect(view.ok).toBe(false);
  });
});
