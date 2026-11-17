import { clientClientPath, http } from "./api";

export type GoogleCampaignPayload = {
  platform: "google_ads";
  name: string; objective: "vendas" | "leads" | "trafego"; type: "SEARCH";
  daily_budget: number; start_date: string; end_date: string; final_url: string;
  locations: string[]; keywords: string[]; headlines: string[]; descriptions: string[]; notes: string;
};
export type GoogleCampaignDraft = {
  id: string; status: "rascunho"; payload: GoogleCampaignPayload;
  created_at: string | null; updated_at: string | null;
  publication_available: false; message: string;
};
const base = (suffix = "") => clientClientPath(`/studio/google-ads${suffix}`);
export const listGoogleCampaignDrafts = () => http<{ drafts: GoogleCampaignDraft[]; publication_available: false }>(base());
export const createGoogleCampaignDraft = (payload: GoogleCampaignPayload) =>
  http<{ draft: GoogleCampaignDraft }>(base(), { method: "POST", body: JSON.stringify({ payload }) });
export const updateGoogleCampaignDraft = (id: string, payload: GoogleCampaignPayload) =>
  http<{ draft: GoogleCampaignDraft }>(base(`/${encodeURIComponent(id)}`), { method: "PUT", body: JSON.stringify({ payload }) });
export const deleteGoogleCampaignDraft = (id: string) =>
  http<{ ok: true }>(base(`/${encodeURIComponent(id)}`), { method: "DELETE" });
