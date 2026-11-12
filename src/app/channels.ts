import { http } from "./api";
import { getActiveClientId } from "./activeClient";

export type ChannelProvider = "tiktok_ads" | "tiktok" | "pinterest" | "linkedin" | "clarity";
export type ChannelTotals = {
  spend: number; impressions: number; clicks: number; conversions: number; days: number;
  latest: Record<string, number | string | null> | null; top: { name: string | null; value: number }[];
};
export type Channel = {
  provider: ChannelProvider; label: string; auth: "oauth" | "token"; app_configured: boolean;
  status: string; account_name: string | null; last_sync_at: string | null; last_error: string | null;
  metrics: Partial<Record<"tiktok_ads" | "tiktok" | "pinterest" | "pinterest_ads" | "linkedin" | "linkedin_ads" | "clarity", ChannelTotals>>;
};

const q = () => `client_id=${encodeURIComponent(getActiveClientId())}`;
export const getChannels = () => http<{ start: string; end: string; channels: Channel[] }>(`/api/channels?${q()}`);
export const startChannel = (p: ChannelProvider) => http<{ authorization_url: string }>(`/api/channels/${p}/start?${q()}`);
export const connectClarity = (token: string, project_name?: string) =>
  http<{ rows: number }>(`/api/channels/clarity/connect?${q()}`, { method: "POST", body: JSON.stringify({ token, project_name: project_name || null }) });
export const syncChannel = (p: ChannelProvider) => http<{ status: string; rows?: number; message?: string }>(`/api/channels/${p}/sync?${q()}`, { method: "POST" });
export const disconnectChannel = (p: ChannelProvider) => http<{ ok: boolean }>(`/api/channels/${p}?${q()}`, { method: "DELETE" });
