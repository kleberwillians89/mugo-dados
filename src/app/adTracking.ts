/** Campaign-scoped tracking settings. Empty values remain opt-in. */
export type TrackingParams = Partial<Record<"utm_source" | "utm_medium" | "utm_campaign" | "utm_content" | "utm_term", string>>;

export const slugForTracking = (value: string) => value.normalize("NFKD")
  .replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 100);

export const trackingSearch = (tracking: TrackingParams) => new URLSearchParams(
  Object.entries(tracking).filter((entry): entry is [string,string] => Boolean(entry[1]?.trim()))
).toString();
