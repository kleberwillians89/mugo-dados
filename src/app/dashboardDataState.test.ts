import { describe, expect, it } from "vitest";
import { hasInstagramSnapshotData } from "./dashboardDataState";

describe("Instagram client-facing data state", () => {
  it("keeps persisted metrics available even when technical coverage is pending", () => {
    expect(hasInstagramSnapshotData({
      summaryHasData: false,
      coveredDays: 0,
      metricValues: [30709, 14983, 36363, 401],
    })).toBe(true);
  });

  it("only waits when there is no persisted snapshot or metric", () => {
    expect(hasInstagramSnapshotData({
      summaryHasData: false,
      coveredDays: 0,
      metricValues: [0, 0, 0],
    })).toBe(false);
  });
});
