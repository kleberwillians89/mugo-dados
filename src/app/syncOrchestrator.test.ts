import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { describeSyncError, isSyncAlreadyRunningError, runExclusiveSync } from "./syncOrchestrator";

describe("runExclusiveSync", () => {
  it("second call with the same identity reuses the in-flight promise (no second task invocation)", async () => {
    let resolveTask: (value: string) => void = () => {};
    const task = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolveTask = resolve;
        })
    );

    const identity = { clientId: "amalie", provider: "meta_ads", connectionId: "conn-1" };
    const first = runExclusiveSync(identity, task);
    const second = runExclusiveSync(identity, task);

    expect(task).toHaveBeenCalledTimes(1);
    resolveTask("ok");
    await expect(first).resolves.toBe("ok");
    await expect(second).resolves.toBe("ok");
  });

  it("different connection_id for the same client/provider does not dedupe", async () => {
    const task = vi.fn(async () => "done");
    await runExclusiveSync({ clientId: "amalie", provider: "meta_ads", connectionId: "conn-1" }, task);
    await runExclusiveSync({ clientId: "amalie", provider: "meta_ads", connectionId: "conn-2" }, task);
    expect(task).toHaveBeenCalledTimes(2);
  });

  it("releases the identity after failure so a later click can try again", async () => {
    const identity = { clientId: "amalie", provider: "ga4", connectionId: null };
    const failing = vi.fn(async () => {
      throw new Error("boom");
    });
    await expect(runExclusiveSync(identity, failing)).rejects.toThrow("boom");

    const succeeding = vi.fn(async () => "ok");
    await expect(runExclusiveSync(identity, succeeding)).resolves.toBe("ok");
    expect(succeeding).toHaveBeenCalledTimes(1);
  });
});

describe("describeSyncError / isSyncAlreadyRunningError", () => {
  it("maps SYNC_ALREADY_RUNNING to a friendly message", () => {
    const error = new ApiError("conflict", { status: 409, code: "SYNC_ALREADY_RUNNING" });
    expect(isSyncAlreadyRunningError(error)).toBe(true);
    expect(describeSyncError(error, "fallback")).toBe("A atualização já está em andamento.");
  });

  it("falls back to the generic message for unknown errors", () => {
    expect(describeSyncError(new Error("network down"), "fallback")).toBe("fallback");
  });
});
