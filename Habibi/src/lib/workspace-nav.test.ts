import { describe, expect, it } from "vitest";

import { parseDeepLinkSearch } from "./workspace-nav";

describe("parseDeepLinkSearch", () => {
  it("reads a new-callback deep link with the customer already chosen", () => {
    expect(parseDeepLinkSearch({ new: true, customerId: "anita-desai" })).toEqual({
      id: undefined,
      new: true,
      customerId: "anita-desai",
      plan: undefined,
    });
  });

  it("drops empty customer ids", () => {
    expect(parseDeepLinkSearch({ customerId: "" }).customerId).toBeUndefined();
  });

  it("opens a payment plan without also opening PTP", () => {
    expect(parseDeepLinkSearch({ plan: true, customerId: "anita-desai" })).toEqual({
      id: undefined,
      new: undefined,
      customerId: "anita-desai",
      plan: true,
    });
  });
});
