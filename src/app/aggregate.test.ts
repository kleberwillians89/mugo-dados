import { describe, expect, it } from "vitest";
import { buildMonthAgg, classifyInstagramMedia } from "./aggregate";
import type { IgMediaItem } from "./types";

const media = (overrides: Partial<IgMediaItem>): IgMediaItem => ({
  id: "media-1",
  media_type: "IMAGE",
  media_product_type: "FEED",
  timestamp: "2026-08-10T12:00:00Z",
  ...overrides,
});

describe("Instagram content classification", () => {
  it("recognizes reels from either Graph API type field and excludes stories", () => {
    expect(classifyInstagramMedia(media({ media_product_type: "REELS" }))).toBe("reel");
    expect(classifyInstagramMedia(media({ media_type: "REELS", media_product_type: "" }))).toBe("reel");
    expect(classifyInstagramMedia(media({ media_type: "STORY" }))).toBe("story");
  });

  it("keeps monthly post/reel counts consistent with the dashboard", () => {
    const result = buildMonthAgg([
      media({ id: "image", media_type: "IMAGE" }),
      media({ id: "carousel", media_type: "CAROUSEL_ALBUM" }),
      media({ id: "reel", media_type: "REELS", media_product_type: "" }),
      media({ id: "feed-video", media_type: "VIDEO", media_product_type: "FEED" }),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ posts: 3, reels: 1 });
  });

  it("builds two persisted months without a history-ready flag", () => {
    const result = buildMonthAgg([
      media({ id: "july", timestamp: "2026-07-15T12:00:00Z" }),
      media({ id: "august", timestamp: "2026-08-10T12:00:00Z", media_product_type: "REELS" }),
    ]);
    expect(result.map((row) => row.month)).toEqual(["2026-07", "2026-08"]);
  });
});
