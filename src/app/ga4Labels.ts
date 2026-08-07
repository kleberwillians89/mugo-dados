// Camada central de apresentação para termos técnicos do GA4. Nenhum
// componente deve traduzir eventos/canais/campanhas por conta própria —
// sempre importar daqui, para manter um único lugar de verdade.

const EVENT_LABELS: Record<string, string> = {
  page_view: "Visualizações de página",
  session_start: "Sessões iniciadas",
  first_visit: "Novos visitantes",
  user_engagement: "Usuários engajados",
  scroll: "Rolagens da página",
  click: "Cliques",
  view_item: "Produtos visualizados",
  view_item_list: "Listas de produtos visualizadas",
  select_item: "Produtos selecionados",
  add_to_cart: "Adições ao carrinho",
  remove_from_cart: "Remoções do carrinho",
  view_cart: "Visualizações do carrinho",
  begin_checkout: "Inícios de checkout",
  add_shipping_info: "Informações de entrega adicionadas",
  add_payment_info: "Informações de pagamento adicionadas",
  purchase: "Compras",
  refund: "Reembolsos",
  generate_lead: "Leads gerados",
  sign_up: "Cadastros",
  login: "Logins",
  search: "Pesquisas realizadas",
  view_search_results: "Resultados de busca visualizados",
  file_download: "Downloads",
  video_start: "Vídeos iniciados",
  video_progress: "Progresso dos vídeos",
  video_complete: "Vídeos concluídos",
  form_start: "Formulários iniciados",
  form_submit: "Formulários enviados",
};

const CHANNEL_LABELS: Record<string, string> = {
  "(direct) / (none)": "Acesso direto",
  "(not set)": "Não identificado",
  organic: "Tráfego orgânico",
  "organic search": "Pesquisa orgânica",
  "paid search": "Pesquisa paga",
  "paid social": "Redes sociais pagas",
  "organic social": "Redes sociais orgânicas",
  referral: "Sites de referência",
  email: "E-mail",
  display: "Mídia display",
  "cross-network": "Campanhas multicanal",
  unassigned: "Não classificado",
  "facebook / paid": "Facebook Ads",
  "instagram / paid": "Instagram Ads",
  "google / cpc": "Google Ads",
  "linktr.ee / referral": "Linktree",
};

function normalizeKey(value: string): string {
  return String(value || "").trim().toLowerCase();
}

/**
 * Nome legível de um evento GA4. Para eventos desconhecidos, converte o
 * identificador técnico (snake_case) em um título capitalizado, nunca
 * mostrando o identificador cru como título principal.
 */
export function getGa4EventLabel(eventName: string | null | undefined): string {
  const raw = String(eventName || "").trim();
  if (!raw) return "Evento personalizado";
  const known = EVENT_LABELS[normalizeKey(raw)];
  if (known) return known;
  return humanizeIdentifier(raw);
}

/** true quando o evento tem tradução conhecida — usado para decidir se mostra o nome técnico como detalhe secundário. */
export function isKnownGa4Event(eventName: string | null | undefined): boolean {
  return normalizeKey(String(eventName || "")) in EVENT_LABELS;
}

/**
 * Nome legível de um canal/origem GA4 (source/medium combinado). Para
 * combinações desconhecidas, mantém o valor original — canais têm menos
 * padrão previsível que eventos, então não tentamos humanizar heuristicamente.
 */
export function getGa4ChannelLabel(sourceMedium: string | null | undefined): string {
  const raw = String(sourceMedium || "").trim();
  if (!raw) return "Não identificado";
  const known = CHANNEL_LABELS[normalizeKey(raw)];
  if (known) return known;
  return raw;
}

/**
 * Classificação canônica de origem (Bloco 5) — GA4 é uma camada de
 * MEDIÇÃO, não uma plataforma de mídia: uma sessão medida pelo GA4 pode
 * ter sido originada por uma campanha Meta, Google Ads, orgânico etc.
 * Nunca inferir o provedor real só pelo campaign_id (o mesmo número pode
 * existir em contas Meta e Google Ads de forma independente) — a
 * classificação usa source/medium, os únicos sinais realmente
 * disponíveis nos relatórios de canal/campanha do GA4 hoje.
 */
export type Ga4CampaignProvider =
  | "meta_ads"
  | "google_ads"
  | "ga4"
  | "shopify"
  | "organic_instagram"
  | "direct"
  | "referral"
  | "email"
  | "other"
  | "unknown";

export function classifyGa4Provider(
  source: string | null | undefined,
  medium: string | null | undefined
): Ga4CampaignProvider {
  const src = String(source || "").trim().toLowerCase();
  const med = String(medium || "").trim().toLowerCase();

  if (!src && !med) return "unknown";
  if ((src === "facebook" || src === "instagram" || src === "ig") && (med.includes("paid") || med === "cpc")) {
    return "meta_ads";
  }
  if (src === "google" && med === "cpc") return "google_ads";
  if (med === "organic" || med.includes("organic search")) return "other";
  if ((src === "instagram" || src === "ig") && med.includes("organic")) return "organic_instagram";
  if (med === "email") return "email";
  if (med === "referral") return "referral";
  if (src === "(direct)" || med === "(none)") return "direct";
  return "unknown";
}

const PROVIDER_LABELS: Record<Ga4CampaignProvider, string> = {
  meta_ads: "Meta Ads",
  google_ads: "Google Ads",
  ga4: "GA4",
  shopify: "Shopify",
  organic_instagram: "Instagram orgânico",
  direct: "Acesso direto",
  referral: "Site de referência",
  email: "E-mail",
  other: "Outra origem",
  unknown: "Origem não identificada",
};

export function getGa4ProviderLabel(provider: Ga4CampaignProvider): string {
  return PROVIDER_LABELS[provider];
}

/**
 * Nome de campanha para exibição. Nunca usa o ID numérico como título
 * principal. Quando só há ID, o fallback inclui o provedor real (deduzido
 * de source/medium) sempre que houver evidência — nunca "Campanha não
 * identificada" quando o provedor for conhecido.
 */
export function getCampaignDisplayName(
  campaignName: string | null | undefined,
  context?: { source?: string | null; medium?: string | null }
): string {
  // "(not set)" é o valor técnico literal que o GA4 retorna para tráfego
  // sem campanha associada — tratado como ausência de nome (igual a um ID
  // numérico sem nome), nunca chega cru na UI.
  const rawInput = String(campaignName || "").trim();
  const raw = rawInput.toLowerCase() === "(not set)" ? "" : rawInput;
  const isNumericOnly = !raw || /^\d+$/.test(raw);
  if (!isNumericOnly) return raw;

  const provider = context ? classifyGa4Provider(context.source, context.medium) : "unknown";
  if (provider === "unknown" || provider === "ga4" || provider === "other") {
    return "Campanha não identificada";
  }
  return raw
    ? `${getGa4ProviderLabel(provider)} — campanha ${raw}`
    : `${getGa4ProviderLabel(provider)} — campanha não identificada`;
}

export function getCampaignIdDetail(campaignId: string | null | undefined): string | null {
  const raw = String(campaignId || "").trim();
  return raw ? `ID da campanha: ${raw}` : null;
}

/** Detalhe técnico secundário — nunca deve virar título principal. */
export function getGa4EventTechnicalDetail(eventName: string | null | undefined): string | null {
  const raw = String(eventName || "").trim();
  if (!raw || isKnownGa4Event(raw)) return null;
  return `Evento técnico: ${raw}`;
}

function humanizeIdentifier(raw: string): string {
  const spaced = raw.replace(/[_-]+/g, " ").trim();
  if (!spaced) return "Evento personalizado";
  return spaced
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
