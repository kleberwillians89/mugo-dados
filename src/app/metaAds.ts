import { clientClientPath, http } from "./api";
import type { TrackingParams } from "./adTracking";

/** Mídia On → Meta Ads: rascunhos de campanha e publicação PAUSADA (só equipe Mugô). */
export type MetaPlacements = {
  mode: "automatic" | "manual";
  platforms: ("instagram" | "facebook" | "messenger" | "audience_network")[];
  instagram: ("stream" | "story" | "reels" | "explore" | "explore_home" | "profile_feed" | "ig_search")[];
  facebook: ("feed" | "story" | "facebook_reels" | "marketplace" | "video_feeds" | "right_hand_column" | "search" | "instream_video" | "profile_feed" | "notification")[];
  messenger?: ("messenger_home" | "story" | "sponsored_messages")[];
  audience_network?: ("classic" | "rewarded_video")[];
};

/** Os 3 níveis do Gerenciador de Anúncios, com os valores da API da Meta (ODAX). */
export type MetaObjective = "OUTCOME_AWARENESS" | "OUTCOME_TRAFFIC" | "OUTCOME_ENGAGEMENT" | "OUTCOME_LEADS" | "OUTCOME_APP_PROMOTION" | "OUTCOME_SALES";
export type MetaLocation = "NONE" | "WEBSITE" | "APP" | "MESSAGING" | "ON_AD" | "ON_POST" | "PHONE_CALL" | "ON_PAGE" | "INSTAGRAM_PROFILE";
export type MetaMessagingApp = "MESSENGER" | "INSTAGRAM_DIRECT" | "WHATSAPP";
export type MetaBidStrategy = "LOWEST_COST_WITHOUT_CAP" | "COST_CAP" | "LOWEST_COST_WITH_BID_CAP" | "LOWEST_COST_WITH_MIN_ROAS";
export type MetaStructure = {
  objective: MetaObjective;
  special_ad_categories: string[];
  budget_level: "campaign" | "adset";
  budget_type: "daily" | "lifetime";
  budget: number;
  bid_strategy: MetaBidStrategy;
  bid_amount: number | null;
  roas_floor: number | null;
  conversion_location: MetaLocation;
  messaging_apps: MetaMessagingApp[];
  performance_goal: string;
  conversion_event: string | null;
  app: { id: string; name: string; store_url: string } | null;
  lead_form: { id: string; name: string } | null;
  phone_number: string | null;
  has_end_date: boolean;
  use_existing_post: boolean;
};
export type MetaCatalog = {
  objectives: { key: MetaObjective; label: string; icon: string; hint: string }[];
  special_categories: { key: string; label: string }[];
  bid_strategies: { key: MetaBidStrategy; label: string; hint: string }[];
  locations: Record<MetaLocation, string>;
  location_order: MetaLocation[];
  messaging_apps: { key: MetaMessagingApp; label: string }[];
  matrix: Record<MetaObjective, Partial<Record<MetaLocation, string[]>>>;
  goals: Record<string, string>;
  events: { key: string; label: string }[];
  ctas: Record<string, string>;
  ctas_by_location: Record<string, string[]>;
};
export type BuilderOptions = {
  catalog: MetaCatalog;
  account: { id: string; name: string; currency: string; timezone: string };
  identity: { page: { id: string; name: string; picture: string }; instagram: { id: string; username: string; picture: string } | null };
  pixels: { id: string; name: string; active: boolean; events_seen: string[] }[];
  recommended_pixel: string | null;
  apps: { id: string; name: string; icon_url: string; stores: { store: string; url: string }[] }[];
  lead_forms: { id: string; name: string; status: string }[];
  whatsapp_numbers: { number: string; label: string; name: string }[];
  preview_formats: { key: string; label: string }[];
};
export type MetaInterest = { id: string; name: string; path: string; size: string };
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
  /** Estrutura igual ao Gerenciador. Rascunhos antigos recebem o bloco equivalente do servidor. */
  meta?: MetaStructure;
  name: string; objective: "trafego" | "alcance" | "engajamento" | "vendas" | "leads" | "whatsapp" | "retencao" | "remarketing"; daily_budget: number; start_date: string; end_date: string;
  audience: {
    age_min: number; age_max: number; gender: "todos" | "mulheres" | "homens"; regions: string[]; interests: string[]; advantage: boolean;
    /** Público salvo da conta: a segmentação dele (idade, locais, interesses) substitui a escrita acima. */
    saved_audience?: AudienceRef | null;
    /** Públicos personalizados/semelhantes da conta somados ao conjunto, e os que ficam de fora. */
    custom_audiences?: AudienceRef[]; excluded_audiences?: AudienceRef[];
    /** Interesses escolhidos na lista oficial da Meta (id exato). */
    interest_refs?: AudienceRef[];
  };
  ad: { primary_text: string; headline: string; description: string; cta: string; link: string; image_url: string; calendar_item_id: string | null; media_type?: "image" | "video"; video_url?: string; video_id?: string | null; instagram_post_id?: string | null; whatsapp_number?: string | null; format?: AdFormat; cards?: AdCard[]; extra_ads?: AdCreative[] };
};
export type AdDraft = {
  id: string; month: string | null; source_campaign: string | null; status: "rascunho" | "publicando" | "publicada" | "erro";
  payload: AdPayload; missing: string[]; meta_ids: Record<string, string>; ads_manager_url: string | null; error: string | null; joined?: boolean;
  published_at: string | null; updated_at: string | null;
};
export type AudienceRef = { id: string; name: string };
/** Público que já existe na conta de anúncios do cliente. ready=false: o Meta não entrega (pequeno ou preparando). */
export type AccountAudience = AudienceRef & { kind: string; kind_label: string; size: string; ready: boolean; status: string; foreign?: boolean };
export type NewAudience = {
  kind: "instagram" | "facebook" | "site" | "compradores" | "semelhante" | "lista";
  name?: string; event?: string; days?: number; url_contains?: string; origin_audience_id?: string; ratio?: number;
};
/** Cria um público na conta de anúncios, como no Gerenciador. */
export function createAdAudience(input: NewAudience) {
  return http<{ id: string; name: string; kind: string; note: string }>(clientClientPath("/studio/ads/audiences"),
    { method: "POST", body: JSON.stringify(input), timeoutMs: 120_000 });
}
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
/** Atualiza verba na Meta e só confirma após read-back do provedor. */
export const updateLiveMetaBudget = (id: string, dailyBudget: number) =>
  http<{ draft: AdDraft; meta_confirmed: true; budget_level: string }>(
    base(`/${encodeURIComponent(id)}/edit-budget`),
    { method: "POST", body: JSON.stringify({ daily_budget: dailyBudget, confirm: true }), timeoutMs: 60_000 }
  );

/** Edição de um único anúncio de imagem: cria novo criativo e substitui referência na Meta. */
export const updateLiveMetaCreative = (id: string, ad: Pick<AdPayload["ad"], "primary_text" | "headline" | "description" | "cta" | "link" | "image_url">) =>
  http<{ draft: AdDraft; meta_confirmed: true; review_may_be_required: true }>(
    base(`/${encodeURIComponent(id)}/edit-creative`),
    { method: "POST", body: JSON.stringify({ ad, confirm: true }), timeoutMs: 120_000 }
  );

/** Estrutura atual da Meta para uma campanha já publicada, carregada no tenant ativo. */
export type LiveMetaObject = {
  id: string; name: string; campaign_id?: string; adset_id?: string;
  status: string; effective_status: string;
  daily_budget?: string | number | null; lifetime_budget?: string | number | null;
  start_time?: string | null; end_time?: string | null;
  creative?: { id?: string; name?: string; thumbnail_url?: string };
};
export type LiveMetaStructure = {
  source: "meta_graph"; checked_at: string; read_only: true;
  ad_account_id: string;
  campaign: LiveMetaObject;
  adsets: (LiveMetaObject & { customer_acquisition_goal?: number | null })[];
  ads: LiveMetaObject[];
};
export const readLiveMetaStructure = (id: string) =>
  http<LiveMetaStructure>(base(`/${encodeURIComponent(id)}/structure`), { timeoutMs: 60_000 });
export const changeLiveMetaObjectStatus = (
  draftId: string, level: "adset" | "ad", objectId: string, status: "ACTIVE" | "PAUSED"
) => http<{ meta_confirmed: true; id: string; status: string; effective_status: string; checked_at: string }>(
  base(`/${encodeURIComponent(draftId)}/objects/${level}/${encodeURIComponent(objectId)}/status`),
  { method: "POST", body: JSON.stringify({ status, confirm: true }), timeoutMs: 60_000 }
);

/** Atualiza somente o orçamento diário de um conjunto pertencente à campanha publicada. */
export const updateLiveMetaAdsetBudget = (draftId: string, adsetId: string, dailyBudget: number) =>
  http<{ meta_confirmed: true; id: string; campaign_id: string; daily_budget: number; budget_level: "adset"; checked_at: string }>(
    base(`/${encodeURIComponent(draftId)}/objects/adset/${encodeURIComponent(adsetId)}/budget`),
    { method: "POST", body: JSON.stringify({ daily_budget: dailyBudget, confirm: true }), timeoutMs: 60_000 }
  );

/** Indicadores Meta reais de um conjunto ou anúncio pertencente à campanha selecionada. Somente leitura. */
export type LiveMetaObjectInsights = {
  source: "meta_graph"; read_only: true; level: "adset" | "ad"; id: string;
  date_preset: "last_7d"; checked_at: string; has_data: boolean;
  spend: number; impressions: number; reach: number; clicks: number; link_clicks: number;
  ctr: number; cpc: number; cpm: number; frequency: number;
  actions: { type: string; value: number }[];
};
export const readLiveMetaObjectInsights = (draftId: string, level: "adset" | "ad", objectId: string) =>
  http<LiveMetaObjectInsights>(
    base(`/${encodeURIComponent(draftId)}/objects/${level}/${encodeURIComponent(objectId)}/insights`),
    { timeoutMs: 60_000 }
  );

/** Descontos oficiais da Shopify vinculada à empresa ativa; exige read_discounts. */
export type ShopPromotionCode = { code: string; title: string; status: string; starts_at: string | null; ends_at: string | null };
export const listShopPromotionCodes = () =>
  http<{ source: "shopify"; codes: ShopPromotionCode[]; read_only: true; partial: boolean }>(
    base("/promotion-codes"), { timeoutMs: 45_000 }
  );

export const deleteAdDraft = (id: string) => http<{ ok: true }>(base(`/${encodeURIComponent(id)}`), { method: "DELETE" });
export const listAdAudiences = () => http<AccountAudiences>(base("/audiences"), { timeoutMs: 60_000 });

/** Read-only Meta readiness. No access tokens or account secrets are exposed. */
export type MetaPublicationPreflight = {
  ready: boolean;
  objective: string;
  checks: { key: string; ok: boolean; message: string; label: string }[];
};
export const metaPublicationPreflight = (objective: AdPayload["objective"], needsPixel?: boolean) =>
  http<MetaPublicationPreflight>(base(`/preflight?objective=${encodeURIComponent(objective)}${needsPixel === undefined ? "" : `&needs_pixel=${needsPixel}`}`), {timeoutMs: 60_000});

/** Opções do criador puxadas da conta Meta desta empresa (pixels, eventos, apps, formulários, identidade). */
export const getBuilderOptions = () => http<BuilderOptions>(base("/options"), { timeoutMs: 60_000 });
/** Só a estrutura (objetivos, locais, metas), sem consultar a conta: usado quando a conta não responde. */
export const getBuilderCatalog = () => http<MetaCatalog>(base("/catalog"));
export const searchMetaInterests = (q: string) =>
  http<{ interests: MetaInterest[] }>(base(`/interests?q=${encodeURIComponent(q)}`), { timeoutMs: 30_000 });
/** Prévia oficial da Meta (iframe do Gerenciador) para o anúncio salvo do rascunho. */
export const getOfficialPreview = (id: string, format: string, ad = 0) =>
  http<{ format: string; label: string; src: string }>(base(`/${encodeURIComponent(id)}/preview?format=${encodeURIComponent(format)}&ad=${ad}`), { timeoutMs: 90_000 });

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
export const duplicateAdDraft = (id: string, into?: "campaign", adsetId?: string) => {
  const params = new URLSearchParams();
  if (into) params.set("into", into);
  if (adsetId) params.set("adset_id", adsetId);
  return http<{ draft: AdDraft }>(base(`/${encodeURIComponent(id)}/duplicate${params.size ? `?${params}` : ""}`), { method: "POST" });
};

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

/** Números de WhatsApp da marca para o anúncio que abre conversa. */
export const readAdWhatsappNumbers = () =>
  http<{ numbers: { number: string; label: string; name: string }[] }>(base("/whatsapp-numbers"));

/** Campanhas que já existem na conta da Meta, para puxar para a Mídia On. */
export type MetaAccountCampaign = { id: string; name: string; objective: string; status: string; daily_budget: number | null; created_time: string | null; imported: boolean };
export const readMetaCampaigns = () => http<{ campaigns: MetaAccountCampaign[] }>(base("/meta-campaigns"), { timeoutMs: 45_000 });
/** Leitura por empresa autorizada para o painel geral da agência. Não altera a seleção ativa. */
export type MetaOverviewCampaign = MetaAccountCampaign & { stop_time?: string | null };
export const readMetaCampaignOverview = (clientId: string) =>
  http<{ campaigns: MetaOverviewCampaign[] }>(
    `/api/clients/${encodeURIComponent(clientId)}/studio/ads/meta-campaigns/overview`,
    { timeoutMs: 60_000 }
  );

export const importMetaCampaign = (campaignId: string) =>
  http<{ draft: AdDraft }>(base("/import"), { method: "POST", body: JSON.stringify({ campaign_id: campaignId }), timeoutMs: 60_000 });

/** Visão do cliente (somente leitura): o que está sendo veiculado no Meta pela Mídia On. */
export type LiveCampaignState = "no_ar" | "pausada" | "em_analise" | "com_problema" | "reprovada" | "encerrada" | "desconhecido";
export type LiveCampaign = {
  id: string; name: string; objective: string; daily_budget: number; start_date: string; end_date: string;
  primary_text: string; headline: string; link: string | null;
  creatives: { format: string; image_url: string | null; video_url: string | null; cards: number | null }[];
  state: LiveCampaignState;
  results: { spend: number; reach: number; impressions: number; link_clicks: number; ctr: number; results: number;
    result_label: string; cost_per_result: number | null; checked_at: string } | null;
};
export function getLiveCampaigns() {
  return http<{ campaigns: LiveCampaign[]; checked_at: string; read_only: true }>(base("/live"), { timeoutMs: 60_000 });
}

/** Leitura da IA das campanhas no ar (Meta da conta inteira + Google), cada campanha julgada pelo próprio objetivo. */
export type LiveReadNumbers = Record<string, number | null>;
export type LiveReadCampaign = { id: string; canal?: "Meta" | "Google"; campanha: string; objetivo: string; veredito: "escalar" | "manter" | "ajustar" | "pausar";
  leitura: string; acao: string; numeros: LiveReadNumbers; ultimos_7_dias: LiveReadNumbers; sinais: string[] };
export type LiveReadNote = { id: string; canal: "Meta" | "Google"; campanha: string; texto: string };
export type LiveRead = { resumo: string | null; campanhas: LiveReadCampaign[]; proximos_passos: string[]; checked_at: string;
  explicacoes?: LiveReadNote[]; melhorias?: LiveReadNote[]; message?: string; cached?: boolean };
export function getLiveRead(refresh = false) {
  return http<LiveRead>(base(`/live-read${refresh ? "?refresh=true" : ""}`), { timeoutMs: 150_000 });
}

/** Mídia On enxuta: só as campanhas ATIVAS agora, com o resultado do objetivo e um sinal por regra fixa (sem IA). */
export type MediaNowSignal = "bem" | "atencao" | "aprendendo";
export type MediaNowCampaign = {
  id: string; canal: "Meta" | "Google"; campanha: string; objetivo: string; investido: number | null; investido_7d: number | null;
  verba_diaria: number | null; dias_no_ar: number | null; fim: string | null; recomendavel: boolean;
  resultado: { label: string; value: number | null; cost_label: string; cost: number | null; roas: number | null };
  sinal: MediaNowSignal; motivo: string;
};
export function getMediaNow() {
  return http<{ campaigns: MediaNowCampaign[]; spend_7d: number; checked_at: string }>(base("/now"), { timeoutMs: 60_000 });
}
