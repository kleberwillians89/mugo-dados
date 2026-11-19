import { clientClientPath, http } from "./api";
import type { TrackingParams } from "./adTracking";

/** Mídia On → Meta Ads: rascunhos de campanha e publicação PAUSADA (só equipe Mugô). */
export type MetaPlacements = {
  mode: "automatic" | "manual";
  platforms: ("instagram" | "facebook")[];
  instagram: ("stream" | "story" | "reels")[];
  facebook: ("feed" | "story" | "facebook_reels")[];
};
/** "single": uma imagem/vídeo · "carousel": um anúncio em carrossel · "multi": um anúncio por imagem no mesmo conjunto. */
export type AdFormat = "single" | "carousel" | "multi";
export type AdCard = { image_url: string; headline?: string; description?: string; link?: string };
export const MAX_AD_CARDS = 10;
/** Até 10 anúncios no mesmo conjunto (mesma verba). O anúncio 1 é o próprio `ad`; os outros guardam só a parte visual. */
export const MAX_ADS = 10;
export type AdCreative = { format: "single" | "carousel"; image_url: string; media_type?: "image" | "video"; video_url?: string;
  instagram_post_id?: string | null; calendar_item_id?: string | null; cards?: AdCard[] };
/** Formato antigo "multi" (um anúncio por imagem) → anúncios de imagem única. */
export function normalizeAdFormats(ad: AdPayload["ad"]): AdPayload["ad"] {
  if (ad.format !== "multi") return ad;
  const [first, ...rest] = ad.cards || [];
  return { ...ad, format: "single", media_type: "image", image_url: first?.image_url || ad.image_url, cards: [],
    extra_ads: [...rest.map((c) => ({ format: "single" as const, image_url: c.image_url })), ...(ad.extra_ads || [])] };
}

export type AdPayload = {
  tracking?: TrackingParams;
  placements?: MetaPlacements;
  /** Conjunto de dados (pixel) escolhido na revisão; vazio = o que está recebendo eventos. */
  pixel_id?: string | null;
  name: string; objective: "trafego" | "alcance" | "engajamento" | "vendas" | "leads"; daily_budget: number; start_date: string; end_date: string;
  audience: {
    age_min: number; age_max: number; gender: "todos" | "mulheres" | "homens"; regions: string[]; interests: string[]; advantage: boolean;
    /** Público salvo da conta: a segmentação dele (idade, locais, interesses) substitui a escrita acima. */
    saved_audience?: AudienceRef | null;
    /** Públicos personalizados/semelhantes da conta somados ao conjunto, e os que ficam de fora. */
    custom_audiences?: AudienceRef[]; excluded_audiences?: AudienceRef[];
  };
  ad: { primary_text: string; headline: string; description: string; cta: string; link: string; image_url: string; calendar_item_id: string | null; media_type?: "image" | "video"; video_url?: string; video_id?: string | null; instagram_post_id?: string | null; format?: AdFormat; cards?: AdCard[]; extra_ads?: AdCreative[] };
};
export type AdDraft = {
  id: string; month: string | null; source_campaign: string | null; status: "rascunho" | "publicando" | "publicada" | "erro";
  payload: AdPayload; missing: string[]; meta_ids: Record<string, string>; ads_manager_url: string | null; error: string | null; joined?: boolean;
  published_at: string | null; updated_at: string | null;
};
export type AudienceRef = { id: string; name: string };
/** Público que já existe na conta de anúncios do cliente. ready=false: o Meta não entrega (pequeno ou preparando). */
export type AccountAudience = AudienceRef & { kind: string; kind_label: string; size: string; ready: boolean; status: string };
export type AccountAudiences = { account: string; saved: AccountAudience[]; custom: AccountAudience[] };
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
export const listAdAudiences = () => http<AccountAudiences>(base("/audiences"), { timeoutMs: 60_000 });

/** Read-only Meta readiness. No access tokens or account secrets are exposed. */
export type MetaPublicationPreflight = {
  ready: boolean;
  objective: string;
  checks: { key: string; ok: boolean; message: string; label: string }[];
};
export const metaPublicationPreflight = (objective: AdPayload["objective"]) =>
  http<MetaPublicationPreflight>(base(`/preflight?objective=${encodeURIComponent(objective)}`), {timeoutMs: 60_000});

/** Instagram posts already synchronized for this selected client. */
export type InstagramCreativePost = {
  id: string;
  media_type: string;
  media_product_type: string;
  caption: string;
  permalink: string | null;
  timestamp: string;
  preview_url: string;
  image_url: string | null;
  video_url?: string | null;
  selectable: boolean;
};
export const listInstagramCreativePosts = () =>
  http<{ posts: InstagramCreativePost[]; source: string; count: number }>(base("/instagram-posts"), { timeoutMs: 45_000 });

/** Independent copy for experimentation. Never duplicates Meta provider resources or starts delivery. */
export const duplicateAdDraft = (id: string, into?: "campaign") =>
  http<{ draft: AdDraft }>(base(`/${encodeURIComponent(id)}/duplicate${into ? "?into=campaign" : ""}`), { method: "POST" });

export type MetaLiveDeliveryStatus = {
  draft_id: string; client_id: string; checked_at: string; source: "meta_graph"; read_only: true;
  objects: Partial<Record<string, {
    id: string; name: string; status: string; effective_status: string;
  }>>;
  delivery?: { state: "ativa" | "pausada"; by: string; at: string } | null;
  joined?: boolean;
};
export type MetaCampaignResults = {
  draft_id: string; period: "today" | "yesterday" | "last_7d" | "maximum"; checked_at: string; currency: "BRL";
  spend: number; impressions: number; reach: number; clicks: number; link_clicks: number; ctr: number; cpc: number | null;
  results: number; result_label: string; cost_per_result: number | null; daily_budget: number;
};
/** Liga a entrega na Meta (começa a gastar). Exige repetir a verba diária como confirmação. */
export const activateAdDraft = (id: string, confirmDailyBudget?: number) =>
  http<MetaLiveDeliveryStatus>(base(`/${encodeURIComponent(id)}/activate`),
    { method: "POST", body: JSON.stringify({ confirm_daily_budget: confirmDailyBudget ?? null }), timeoutMs: 60_000 });
export const pauseAdDraft = (id: string) =>
  http<MetaLiveDeliveryStatus>(base(`/${encodeURIComponent(id)}/pause`), { method: "POST", timeoutMs: 60_000 });
export const readAdResults = (id: string, period: MetaCampaignResults["period"] = "maximum") =>
  http<MetaCampaignResults>(base(`/${encodeURIComponent(id)}/results?period=${period}`), { timeoutMs: 45_000 });
export const readMetaLiveDeliveryStatus = (id: string) =>
  http<MetaLiveDeliveryStatus>(base(`/${encodeURIComponent(id)}/delivery-status`), { timeoutMs: 45_000 });


/** Conjuntos de dados (pixels) da conta de anúncios. */
export type AdPixels = { current: string | null; recommended: string | null; ads_not_updated?: number;
  pixels: { id: string; name: string; last_fired_time: string | null; active: boolean; unavailable: boolean }[] };
export const readAdPixels = (draftId?: string) =>
  http<AdPixels>(base(`/pixels${draftId ? `?draft_id=${encodeURIComponent(draftId)}` : ""}`), { timeoutMs: 45_000 });
export const changeAdPixel = (draftId: string, pixelId: string) =>
  http<AdPixels>(base(`/${encodeURIComponent(draftId)}/pixel`), { method: "POST", body: JSON.stringify({ pixel_id: pixelId }), timeoutMs: 60_000 });
export const PIXEL_OBJECTIVES = ["leads", "vendas", "retencao", "remarketing"];
