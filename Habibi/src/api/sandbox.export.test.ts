// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// The call-report export URL.
//
// Replaces a source-grep in sandbox.test.ts that matched the template literal
// in `sandbox.ts` with a regex. That assertion broke on any reformatting and
// held for none of the things that matter: whether the id is encoded, whether
// the format reaches the query string, whether the response's filename is used.
//
// The rule it also carried — no raw `fetch` in a route — is now
// `scripts/check-layering.mjs`, which checks every route rather than the single
// file the test named.
// -----------------------------------------------------------------------------
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGetBlob = vi.hoisted(() => vi.fn());

vi.mock("./config", () => ({
  apiGetBlob,
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  apiUpload: vi.fn(),
  retryUnlessClientError: () => false,
}));

const { exportInteraction } = await import("./sandbox");

describe("exportInteraction", () => {
  beforeEach(() => {
    apiGetBlob.mockResolvedValue({
      blob: new Blob(["report"]),
      headers: new Headers({ "Content-Disposition": 'attachment; filename="call-CL-1.md"' }),
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  });

  afterEach(() => vi.restoreAllMocks());

  it("encodes the interaction id into the path and passes the format", async () => {
    await exportInteraction("CL/1 2", "json");

    // A slash in an id would otherwise open a different route entirely.
    expect(apiGetBlob).toHaveBeenCalledWith("/interactions/CL%2F1%202/export?format=json");
  });

  it("names the file from Content-Disposition, falling back to the id", async () => {
    const anchor = { href: "", download: "", click: vi.fn() };
    vi.spyOn(document, "createElement").mockReturnValue(anchor as unknown as HTMLAnchorElement);

    await exportInteraction("CL-1", "md");
    expect(anchor.download).toBe("call-CL-1.md");

    apiGetBlob.mockResolvedValue({ blob: new Blob([""]), headers: new Headers() });
    await exportInteraction("CL-2", "json");
    expect(anchor.download).toBe("call-CL-2.json");
  });
});
