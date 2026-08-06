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
 * Nome de campanha para exibição. Nunca usa o ID numérico como título
 * principal — quando só há ID, retorna "Campanha não identificada" e quem
 * chama deve mostrar o ID como detalhe secundário via getCampaignIdDetail.
 */
export function getCampaignDisplayName(campaignName: string | null | undefined): string {
  const raw = String(campaignName || "").trim();
  if (!raw) return "Campanha não identificada";
  // Alguns relatórios da Meta/GA4 retornam só o ID numérico como "nome".
  if (/^\d+$/.test(raw)) return "Campanha não identificada";
  return raw;
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
