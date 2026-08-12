import type { IgMediaItem } from "./types";

export const CONTENT_METRICS = [
  "reach", "views", "likes", "comments", "shares", "saved",
  "total_interactions", "profile_visits",
] as const;
export type ContentMetric = (typeof CONTENT_METRICS)[number];

export type MetricCoverage = { value: number | null; availableCount: number; eligibleCount: number };

function availableMetrics(media: IgMediaItem): Set<string> {
  const available = media.insights?.available_metrics;
  return new Set(Array.isArray(available) ? available.map(String) : []);
}

export function isInstagramStory(media: IgMediaItem) {
  return String(media.media_product_type || media.media_type || "").toUpperCase() === "STORY";
}

export function aggregateInstagramOrganic(media: IgMediaItem[]) {
  const content = media.filter((item) => !isInstagramStory(item));
  const stories = media.filter(isInstagramStory);
  const metrics = Object.fromEntries(CONTENT_METRICS.map((metric) => {
    let value = 0;
    let availableCount = 0;
    content.forEach((item) => {
      if (!availableMetrics(item).has(metric)) return;
      const raw = item.insights?.[metric];
      if (typeof raw !== "number" || !Number.isFinite(raw)) return;
      value += raw;
      availableCount += 1;
    });
    return [metric, { value: availableCount ? value : null, availableCount, eligibleCount: content.length }];
  })) as Record<ContentMetric, MetricCoverage>;
  return {
    content,
    stories,
    eligibleContentCount: content.length,
    contentWithInsightsCount: content.filter((item) => availableMetrics(item).size > 0).length,
    reelsCount: content.filter((item) => String(item.media_product_type).toUpperCase() === "REELS").length,
    feedCount: content.filter((item) => String(item.media_product_type).toUpperCase() !== "REELS").length,
    metrics,
    storyWithInsightsCount: stories.filter((item) => availableMetrics(item).size > 0).length,
  };
}

export function topInstagramContent(media: IgMediaItem[], metric: ContentMetric, limit = 6) {
  return media
    .filter((item) => !isInstagramStory(item) && availableMetrics(item).has(metric))
    .filter((item) => typeof item.insights?.[metric] === "number")
    .sort((a, b) => Number(b.insights?.[metric]) - Number(a.insights?.[metric]))
    .slice(0, limit);
}
