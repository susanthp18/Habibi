// @vitest-environment jsdom
// -----------------------------------------------------------------------------
// Releasing a skill zip's object URL, and when.
//
// Replaces a source-grep in studio-contract.test.ts that asserted the file
// contained "revokeObjectURL" and "setTimeout" — two strings that say nothing
// about ordering, which is the entire property. Revoking in the same tick
// aborts the download in Chromium, so what matters is that the revoke happens
// *after* the click and not before.
//
// Fake timers rather than a 60-second wait.
// -----------------------------------------------------------------------------
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiGetBlob = vi.hoisted(() => vi.fn());

// `./config` is where the transport lives, and `agent-studio.ts` pulls its
// whole surface from there — a partial mock would fail at import, not at the
// assertion.
vi.mock("./config", () => ({
  apiGetBlob,
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  apiUpload: vi.fn(),
  retryUnlessClientError: () => false,
}));

const { exportSkillZip, invalidateAgentStudio } = await import("./agent-studio");

describe("exportSkillZip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    apiGetBlob.mockResolvedValue({
      blob: new Blob(["zip"]),
      headers: new Headers({ "Content-Disposition": 'attachment; filename="ptp-negotiate.zip"' }),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("revokes the object URL only after the download has had time to start", async () => {
    const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const click = vi.fn();
    vi.spyOn(document, "createElement").mockReturnValue({
      href: "",
      download: "",
      click,
    } as unknown as HTMLAnchorElement);

    await exportSkillZip("skill-1");

    expect(create).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    // The whole point: still live at the moment the click returns.
    expect(revoke).not.toHaveBeenCalled();

    vi.advanceTimersByTime(60_000);
    expect(revoke).toHaveBeenCalledWith("blob:fake");
  });

  it("takes the filename from Content-Disposition", async () => {
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const anchor = { href: "", download: "", click: vi.fn() };
    vi.spyOn(document, "createElement").mockReturnValue(anchor as unknown as HTMLAnchorElement);

    await exportSkillZip("skill-1");

    expect(anchor.download).toBe("ptp-negotiate.zip");
  });
});

describe("invalidateAgentStudio", () => {
  it("invalidates every key a studio write can stale, including the skills list", () => {
    // Replaces a source-grep that read `agent-studio.skills.index.tsx` for the
    // strings "invalidateAgentStudio" and "onSubmit" — which would still pass
    // if the call were in a comment, and says nothing about which keys move.
    // Importing a skill has to refresh the studio list; that is the `agent-studio`
    // key, and it is the one a reader most easily drops from this list.
    const invalidateQueries = vi.fn();
    invalidateAgentStudio({ invalidateQueries } as never);

    const keys = invalidateQueries.mock.calls.map(
      (c) => (c[0] as { queryKey: string[] }).queryKey[0],
    );
    expect(keys).toContain("agent-studio");
    // Both deployment roots: experiments live under ["deployments"] and the
    // rows themselves under ["bot-deployments"], so a rollback that refreshed
    // one left the other on screen contradicting it.
    expect(keys).toEqual(
      expect.arrayContaining([
        "agent-change-log",
        "deployments",
        "bot-deployments",
        "eval-reports",
      ]),
    );
  });
});
