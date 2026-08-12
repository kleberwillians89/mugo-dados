import { describe, expect, it } from "vitest";
import type { DashboardDailyMetric } from "./DashboardDataContext";
import { followerGrowthForPeriod } from "./followerGrowth";

const snapshot = (date: string, followers: number) => ({
  metric_date: date,
  instagram_followers: followers,
} as DashboardDailyMetric);

describe("followerGrowthForPeriod", () => {
  it("usa o último snapshot anterior ao início como baseline", () => {
    expect(followerGrowthForPeriod([
      snapshot("2026-05-31", 100), snapshot("2026-06-15", 110), snapshot("2026-06-30", 120),
    ], "2026-06-01", "2026-06-30")).toEqual({ current: 120, delta: 20, percent: 20, label: "no período" });
  });

  it("explicita desde quando mede quando não existe baseline anterior", () => {
    expect(followerGrowthForPeriod([
      snapshot("2026-06-10", 100), snapshot("2026-06-30", 110),
    ], "2026-06-01", "2026-06-30")).toEqual({ current: 110, delta: 10, percent: 10, label: "desde 10/06" });
  });

  it("não inventa crescimento com apenas um snapshot", () => {
    expect(followerGrowthForPeriod([
      snapshot("2026-06-30", 110),
    ], "2026-06-01", "2026-06-30")).toEqual({ current: 110, delta: null, percent: null, label: null });
  });
});
