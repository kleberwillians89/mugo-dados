import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("./Dashboard.tsx", import.meta.url), "utf8");
const refreshBody = source.split("async function onRefresh()", 2)[1]?.split("const hasDash", 1)[0] || "";

describe("Dashboard manual refresh contract", () => {
  it("discovers and runs every operational provider independently", () => {
    for (const call of [
      "refreshAll(",
      "syncAds(",
      "syncShopifyConnection(",
      "syncGa4(",
      "syncGoogleConnection(",
    ]) {
      expect(refreshBody).toContain(call);
    }
    expect(refreshBody).toContain("Promise.allSettled(syncTasks.map");
  });

  it("replaces the preserved snapshot with one read-model refetch", () => {
    expect(refreshBody.match(/dashboardSnapshot\.refetch\(\)/g)).toHaveLength(1);
    expect(refreshBody).not.toContain("reloadExecutive(");
    expect(refreshBody).not.toContain("reloadPaid(");
    expect(refreshBody).not.toContain("reloadSummary(");
  });
});
