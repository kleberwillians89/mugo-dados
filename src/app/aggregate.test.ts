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
      media({ id: "post" }),
      media({ id: "reel", media_type: "REELS", media_product_type: "" }),
      media({ id: "story", media_type: "STORY" }),
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ posts: 1, reels: 1 });
  });
});
