import { clientClientPath, http } from "./api";

export type GoogleCampaignPayload = {
  platform: "google_ads";
  networks?: { google_search: true; search_partners: boolean; display_network: boolean };
  name: string; objective: "vendas" | "leads" | "trafego"; type: "SEARCH";
  daily_budget: number; start_date: string; end_date: string; final_url: string;
  locations: string[]; keywords: string[]; headlines: string[]; descriptions: string[]; notes: string;
  contains_eu_political_advertising: boolean | null;
};
export type GoogleCampaignDraft = {
  id: string; status: "rascunho" | "publicando" | "publicada" | "erro"; payload: GoogleCampaignPayload;
  created_at: string | null; updated_at: string | null;
  publication_available: boolean; message: string;
  external_ids?: Record<string, unknown>; error?: string | null;
  published_at?: string | null; ads_manager_url?: string | null;
};
const base = (suffix = "") => clientClientPath(`/studio/google-ads${suffix}`);
export const listGoogleCampaignDrafts = () => http<{ drafts: GoogleCampaignDraft[]; publication_available: boolean }>(base());
export const getGoogleCampaignPublicationContext = () =>
  http<{ connection_id: string; account: string; customer_id_suffix: string }>(base("/publication-context"));
export const createGoogleCampaignDraft = (payload: GoogleCampaignPayload) =>
  http<{ draft: GoogleCampaignDraft }>(base(), { method: "POST", body: JSON.stringify({ payload }) });
export const updateGoogleCampaignDraft = (id: string, payload: GoogleCampaignPayload) =>
  http<{ draft: GoogleCampaignDraft }>(base(`/${encodeURIComponent(id)}`), { method: "PUT", body: JSON.stringify({ payload }) });
export const deleteGoogleCampaignDraft = (id: string) =>
  http<{ ok: true }>(base(`/${encodeURIComponent(id)}`), { method: "DELETE" });
export const publishGoogleCampaignDraft = (id: string) =>
  http<{ draft: GoogleCampaignDraft }>(base(`/${encodeURIComponent(id)}/publish`), { method: "POST", timeoutMs: 180_000 });
