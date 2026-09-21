// -----------------------------------------------------------------------------
// WP-047: a failed list read must not render as an empty-state lecture.
// RecordsTable / FilterTable had no error slot, so consent said "no records
// match" and payment plans said "create a plan" when the API 500'd.
// vitest is environment: "node" — pin the source the way the Field-label
// suite pins htmlFor.
// -----------------------------------------------------------------------------

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), "../..");

function read(rel: string): string {
  return readFileSync(join(srcRoot, rel), "utf8");
}

describe("QueryErrorBanner names a 403 as no access", () => {
  it("branches on isForbidden instead of treating it as a failed read", () => {
    const banner = read("components/ui/query-state.tsx");
    expect(banner).toContain("isForbidden");
    expect(banner).toContain("isUnauthorized");
    expect(banner).toContain("NoAccess");
  });
});

describe("RecordsTable error slot", () => {
  const table = read("components/records/RecordsTable.tsx");

  it("declares isError so a failed read has somewhere to go", () => {
    expect(table).toContain("isError?: boolean");
    expect(table).toContain("showError");
  });

  it("does not render emptyMessage on a failed read", () => {
    expect(table).toContain("{!isLoading && !showError && visibleRows.length === 0 && (");
    expect(table).toContain("<QueryErrorBanner label={errorLabel} error={error} />");
  });
});

describe("FilterTable loading and error slots", () => {
  const table = read("components/records/FilterTable.tsx");

  it("declares isLoading and isError", () => {
    expect(table).toContain("isLoading?: boolean");
    expect(table).toContain("isError?: boolean");
  });

  it("does not render emptyMessage during load or on a failed read", () => {
    expect(table).toContain("{!isLoading && !showError && visibleCount === 0 && (");
    expect(table).toContain("<QueryErrorBanner label={errorLabel} error={error} />");
  });
});

describe("compliance surfaces thread the error", () => {
  it("consent registry does not default a failed read to []", () => {
    const page = read("routes/_app.consent.tsx");
    expect(page).not.toContain("data: items = []");
    expect(page).toContain("isError={isError}");
    expect(read("components/consent/ConsentTable.tsx")).toContain('errorLabel="consent records"');
  });

  it("compliance dashboard does not render measured zeroes on a 500", () => {
    const page = read("routes/_app.compliance.tsx");
    expect(page).not.toContain("data: items = []");
    expect(page).toContain('label="compliance violations"');
  });

  it("ApprovalsQueue does not disappear on a failed read", () => {
    const queue = read("components/floor/ApprovalsQueue.tsx");
    expect(queue).toContain("if (isError)");
    expect(queue).toContain('label="pending approvals"');
    expect(queue).not.toMatch(/const \{ data = \[\] \} = useFloorApprovals/);
  });

  it("ledger and EMI tables pass isError into FilterTable", () => {
    expect(read("components/customer360/LedgerTab.tsx")).toContain(
      'errorLabel="the account ledger"',
    );
    expect(read("components/customer360/EmiTab.tsx")).toContain(
      'errorLabel="the installment schedule"',
    );
  });

  it("payment plans do not instruct the agent to create a duplicate on a 500", () => {
    const table = read("components/promises/PaymentPlansTable.tsx");
    expect(table).toContain('errorLabel="payment plans"');
    expect(table).toContain("isError={isError}");
  });

  it("assigned queue routes a failed read through QueryErrorBanner", () => {
    const queue = read("components/workspace/AssignedQueue.tsx");
    expect(queue).toContain('<QueryErrorBanner label="your queue" error={error} />');
    expect(queue).not.toContain("Couldn&rsquo;t load your queue.");
  });

  it("the signed-in shell asks first-login and inactive operators to request access", () => {
    const shell = read("routes/_app.tsx");
    expect(shell).toContain("AccessGate");
    expect(read("components/access/AccessGate.tsx")).toContain("needsAccessRequest");
    expect(read("components/access/NoAccess.tsx")).toContain("Request access");
    expect(read("components/access/NoAccess.tsx")).not.toContain("refusedSignIn ? null");
  });
});
