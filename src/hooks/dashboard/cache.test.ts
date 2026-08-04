// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { buildDashboardCacheKey, readDashboardCache, writeDashboardCache } from "./cache";

afterEach(() => {
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("dashboard cache TTL", () => {
  it("honors the requested TTL instead of retaining stale data for fifteen minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-04T12:00:00Z"));
    const key = buildDashboardCacheKey("ga4", { clientId: "amalie" });
    writeDashboardCache(key, { sessions: 10 }, 180_000);
    expect(readDashboardCache(key)).toEqual({ sessions: 10 });
    vi.advanceTimersByTime(180_001);
    expect(readDashboardCache(key)).toBeNull();
  });
});
