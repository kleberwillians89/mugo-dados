import { clientClientPath, http } from "./api";

/** Mídia On → Meta Ads: rascunhos de campanha e publicação PAUSADA (só equipe Mugô). */
export type AdPayload = {
  name: string; objective: "trafego" | "alcance" | "engajamento" | "vendas" | "leads"; daily_budget: number; start_date: string; end_date: string;
  audience: { age_min: number; age_max: number; gender: "todos" | "mulheres" | "homens"; regions: string[]; interests: string[]; advantage: boolean };
  ad: { primary_text: string; headline: string; description: string; cta: string; link: string; image_url: string; calendar_item_id: string | null };
};
export type AdDraft = {
  id: string; month: string | null; source_campaign: string | null; status: "rascunho" | "publicando" | "publicada" | "erro";
  payload: AdPayload; missing: string[]; meta_ids: Record<string, string>; ads_manager_url: string | null; error: string | null;
  published_at: string | null; updated_at: string | null;
};
export type AdsList = { drafts: AdDraft[]; objectives: Record<string, string>; ctas: Record<string, string> };

const base = (path = "") => clientClientPath(`/studio/ads${path}`);
export const listAdDrafts = () => http<AdsList>(base());
export const generateAdDraft = (input: { month?: string; objective: string; days_left: number; campaign: Record<string, unknown> }) =>
  http<{ draft: AdDraft }>(base(), { method: "POST", body: JSON.stringify(input), timeoutMs: 120_000 });
export const saveAdDraft = (id: string, payload: AdPayload) =>
  http<{ draft: AdDraft }>(base(`/${encodeURIComponent(id)}`), { method: "PUT", body: JSON.stringify({ payload }) });
export const publishAdDraft = (id: string) =>
  http<{ draft: AdDraft }>(base(`/${encodeURIComponent(id)}/publish`), { method: "POST", timeoutMs: 180_000 });
export const deleteAdDraft = (id: string) => http<{ ok: true }>(base(`/${encodeURIComponent(id)}`), { method: "DELETE" });
