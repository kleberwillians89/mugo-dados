import { http, clientClientPath } from "./api";

export type CreatorNetwork = "instagram" | "youtube" | "tiktok";
export const CREATOR_NETWORKS: Record<CreatorNetwork, string> = { instagram: "Instagram", youtube: "YouTube", tiktok: "TikTok" };
export const CREATOR_SOURCES: Record<string, string> = {
  meta_business_discovery: "Meta (oficial)", youtube_data_api: "YouTube (oficial)",
  apify_instagram_hashtag: "Apify · hashtag", apify_tiktok: "Apify · TikTok",
};
export const ITEM_STATUS = { candidate: "Candidato", contacted: "Contatado", approved: "Aprovado", rejected: "Recusado" } as const;
export type ItemStatus = keyof typeof ITEM_STATUS;

export type Creator = {
  id: string; network: CreatorNetwork; handle: string; display_name: string | null; profile_url: string | null;
  avatar_url: string | null; biography: string | null; followers: number | null; media_count: number | null;
  avg_likes: number | null; avg_comments: number | null; avg_views: number | null; engagement_rate: number | null;
  engagement_method: string | null; sample_size: number; missing_fields: string[]; source: string; collected_at: string;
  cached?: boolean;
};
export type Shortlist = { id: string; name: string; campaign_type: "ugc" | "influencer"; notes: string | null; created_at: string };
export type ShortlistItem = { id: string; status: ItemStatus; notes: string | null; creator_id: string; creators: Creator | null };
export type CreatorUsage = {
  apify: { month_spent_usd: number; month_budget_usd: number; blocked: boolean };
  youtube: { today_units: number; daily_units_limit: number };
  meta: { month_calls_this_client: number };
};

const path = (suffix = "") => clientClientPath(`/creators${suffix}`);
const post = (body: unknown, timeoutMs?: number) => ({ method: "POST", body: JSON.stringify(body), timeoutMs });
// IA + conferência na Meta e execuções Apify passam do timeout padrão de 25 s.
const SLOW_MS = 150_000;

export const listCreators = (network?: CreatorNetwork, q?: string) => {
  const query = new URLSearchParams(); if (network) query.set("network", network); if (q) query.set("q", q);
  return http<{ creators: Creator[] }>(path(query.size ? `?${query}` : ""));
};
export const lookupCreator = (network: CreatorNetwork, handle: string, force = false) => http<Creator>(path("/lookup"), post({ network, handle, force }));
export const searchCreators = (network: CreatorNetwork, query: string, limit = 10) =>
  http<{ creators: Creator[]; notes: string[] }>(path("/search"), post({ network, query, limit }, 240_000));
export type CreatorSuggestion = { creator: Creator; reason: string };
export const suggestCreators = (campaign_type: Shortlist["campaign_type"], brief: string, count = 6) =>
  http<{ suggestions: CreatorSuggestion[]; discarded: string[]; context_available: boolean }>(path("/suggest"), post({ campaign_type, brief: brief.trim() || null, count }, SLOW_MS));
export const refreshCreator = (id: string) => http<Creator>(path(`/${encodeURIComponent(id)}/refresh`), { method: "POST" });
export const compareCreators = (ids: string[]) => http<{ creators: Creator[] }>(path("/compare"), post({ creator_ids: ids }));
export const getCreatorUsage = () => http<CreatorUsage>(path("/usage"));
export const listShortlists = () => http<{ shortlists: Shortlist[] }>(path("/shortlists"));
export const createShortlist = (name: string, campaign_type: Shortlist["campaign_type"]) => http<Shortlist>(path("/shortlists"), post({ name, campaign_type }));
export const getShortlist = (id: string) => http<Shortlist & { items: ShortlistItem[] }>(path(`/shortlists/${encodeURIComponent(id)}`));
export const addToShortlist = (id: string, creatorId: string) => http(path(`/shortlists/${encodeURIComponent(id)}/items`), post({ creator_id: creatorId }));
export const updateShortlistItem = (id: string, itemId: string, status: ItemStatus) =>
  http(path(`/shortlists/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`), { method: "PATCH", body: JSON.stringify({ status }) });
export const removeFromShortlist = (id: string, itemId: string) =>
  http(path(`/shortlists/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}`), { method: "DELETE" });

const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
export function creatorCompact(value: number | null | undefined) {
  return value == null ? "—" : compact.format(value);
}

export function creatorNumber(value: number | null | undefined, suffix = "") {
  return value == null ? "—" : value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + suffix;
}
