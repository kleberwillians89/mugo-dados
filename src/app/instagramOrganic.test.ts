import { describe, expect, it } from "vitest";
import type { IgMediaItem } from "./types";
import { aggregateInstagramOrganic, topInstagramContent } from "./instagramOrganic";

function media(id: string, kind: string, metrics: Record<string, number> = {}): IgMediaItem {
  return { id, media_type: kind, media_product_type: kind, timestamp: "2026-08-05T12:00:00Z", insights: Object.keys(metrics).length ? { ...metrics, available_metrics: Object.keys(metrics) } : {} };
}

describe("Instagram organic aggregation", () => {
  it("keeps stories separate from Feed/Reels coverage", () => {
    const rows = [...Array.from({ length: 4 }, (_, index) => media(`r${index}`, "REELS", { reach: 10 })), media("f", "FEED", { reach: 10 }), ...Array.from({ length: 6 }, (_, index) => media(`s${index}`, "STORY"))];
    const result = aggregateInstagramOrganic(rows);
    expect(result.eligibleContentCount).toBe(5);
    expect(result.metrics.reach).toEqual({ value: 50, availableCount: 5, eligibleCount: 5 });
    expect(result.stories).toHaveLength(6);
    expect(result.storyWithInsightsCount).toBe(0);
  });

  it("preserves explicit zero and unavailable as different states", () => {
    const result = aggregateInstagramOrganic([media("zero", "FEED", { likes: 0 }), media("other", "REELS", { reach: 2 })]);
    expect(result.metrics.likes.value).toBe(0);
    expect(result.metrics.likes.availableCount).toBe(1);
    expect(result.metrics.views.value).toBeNull();
    expect(result.metrics.views.availableCount).toBe(0);
  });

  it("ranks only eligible content with the selected metric", () => {
    const rows = [media("one", "FEED", { saved: 2 }), media("two", "REELS", { saved: 5 }), media("story", "STORY", { saved: 99 }), media("missing", "FEED", { reach: 20 })];
    expect(topInstagramContent(rows, "saved").map((item) => item.id)).toEqual(["two", "one"]);
  });
});
