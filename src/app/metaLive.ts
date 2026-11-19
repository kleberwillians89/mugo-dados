import { http, clientClientPath } from "./api";

/** Tela Meta (padrão Mídia On): leitura ao vivo da conta de anúncios. Nada é escrito na Meta. */
export type MetaMetrics = {
  spend: number; impressions: number; reach: number; clicks: number; ctr: number; cpm: number; frequency: number;
  purchases: number; revenue: number; roas: number; leads: number; cost_per_purchase: number | null; cost_per_lead: number | null;
};
export type MetaRank = { score: number; label: string } | null;
export type MetaCampaign = {
  id: string; name: string; objective: string; status: string; status_label: string; daily_budget: number | null;
  ads: number; adsets: number; metrics: MetaMetrics;
  quality: { quality: MetaRank; engagement: MetaRank; conversion: MetaRank };
  video: { plays: number; thruplays: number; p25: number; p50: number; p75: number; p100: number; cost_per_thruplay: number | null } | null;
  creative: { thumbnail: string | null; title: string; body: string } | null;
  ads_manager_url: string;
};
export type MetaSlice = { label: string; spend: number; purchases: number; revenue: number; spend_share: number; purchase_share: number; roas: number; cost_per_purchase: number | null };
export type MetaRecommendation = { kind: "fatigue" | "scale" | "audience" | "quality"; tone: "ok" | "warn" | "bad"; title: string; text: string; campaign_id?: string; action: string };
export type MetaLiveOverview = {
  period: { since: string; until: string };
  account: MetaMetrics;
  campaigns: MetaCampaign[];
  breakdowns: { age_gender: MetaSlice[]; age: MetaSlice[]; placement: MetaSlice[]; region: MetaSlice[]; device: MetaSlice[] };
  recommendations: MetaRecommendation[];
  unavailable: string[];
  loaded_at: number;
};
export type MetaFeature = { key: string; label: string; scopes: string[]; state: "ok" | "missing" | "unknown" | "not_connected"; missing: string[]; effect: string };
export type MetaPermissions = {
  features: MetaFeature[];
  connections: { paid: { connected: boolean; ad_account?: string | null }; organic: { connected: boolean; username?: string | null; page?: boolean } };
};

const base = (path = "") => clientClientPath(`/meta/live${path}`);
export const getMetaPermissions = () => http<MetaPermissions>(base("/permissions")).then(normalizePermissions);

const list = <T,>(value: unknown): T[] => (Array.isArray(value) ? value as T[] : []);
export function normalizePermissions(raw: unknown): MetaPermissions {
  const v = (raw && typeof raw === "object" ? raw : {}) as Partial<MetaPermissions>;
  const c = (v.connections || {}) as Partial<MetaPermissions["connections"]>;
  return { features: list<MetaFeature>(v.features).filter((f) => f && f.key && f.state),
    connections: { paid: c.paid || { connected: false }, organic: c.organic || { connected: false } } };
}
