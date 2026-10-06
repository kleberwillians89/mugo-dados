import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const source = readFileSync(new URL("./Dashboard.tsx", import.meta.url), "utf8");
const refreshBody = source.split("async function onRefresh()", 2)[1]?.split("const hasDash", 1)[0] || "";

describe("Dashboard manual refresh contract", () => {
  it("refresh de Meta usa somente a fachada Meta", () => {
    expect(refreshBody).toContain('refreshProviderData("meta", period)');
    for (const call of ["refreshAll(", "syncAds(", "syncShopifyConnection(", "syncGa4(", "syncGoogleConnection("]) {
      expect(refreshBody).not.toContain(call);
    }
  });

  it("replaces the preserved snapshot with one read-model refetch", () => {
    expect(refreshBody.match(/dashboardSnapshot\.refetch\(/g)).toHaveLength(1);
    expect(refreshBody).not.toContain("reloadExecutive(");
    expect(refreshBody).not.toContain("reloadPaid(");
    expect(refreshBody).toContain("reloadSummary({ snapshot, force: true, includeSecondary: true, loadStories: true })");
    expect(refreshBody).toContain("if (!snapshot) throw");
  });
});
