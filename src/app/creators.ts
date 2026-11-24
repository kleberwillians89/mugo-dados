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
// apify/youtube só vêm para a agência (custos da conta Mugô).
export type CreatorUsage = {
  apify?: { month_spent_usd: number; month_budget_usd: number; blocked: boolean };
  youtube?: { today_units: number; daily_units_limit: number };
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
/** Sugestões enquanto digita: criadores salvos e a prévia do @ exato (Meta, grátis). */
export type CreatorPick = { id?: string; network: CreatorNetwork; handle: string; display_name: string | null; avatar_url: string | null;
  followers: number | null; engagement_rate?: number | null; verified?: boolean; private?: boolean; missing?: boolean; reason?: string };
export const resolveCreator = (network: CreatorNetwork, q: string) =>
  http<{ saved: CreatorPick[]; exact: CreatorPick | null; similar?: CreatorPick[] }>(path(`/resolve?${new URLSearchParams({ network, q })}`));
/** Busca por NOME no Instagram (Apify, só a equipe Mugô). */
export const searchPeople = (query: string) => http<{ query: string; people: CreatorPick[] }>(path("/people-search"), post({ query }, SLOW_MS));
export type CreatorSuggestion = { creator: Creator; reason: string; fit?: number | null };
/** Perfis que existem mas a IA tirou da lista, agrupados pelo motivo (poucos seguidores, sem posts recentes...). */
export type SuggestFiltered = Record<string, string[]>;
export const suggestCreators = (campaign_type: Shortlist["campaign_type"], brief: string, count = 6) =>
  http<{ suggestions: CreatorSuggestion[]; discarded: string[]; filtered?: SuggestFiltered; context_available: boolean }>(path("/suggest"), post({ campaign_type, brief: brief.trim() || null, count }, SLOW_MS));
export const refreshCreator = (id: string) => http<Creator>(path(`/${encodeURIComponent(id)}/refresh`), { method: "POST" });
// Cliente: tira o criador da lista da empresa. Agência: exclui do banco inteiro.
export const deleteCreator = (id: string) => http<{ ok: true; scope: "company" | "bank" }>(path(`/${encodeURIComponent(id)}`), { method: "DELETE" });
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

/** Mídia kit e valores do criador nesta empresa (migração 000144). Valores são da marca: cada cliente vê só os seus. */
export type KitPrice = { deliverable: string; amount: number | null; notes?: string | null };
export type KitFile = { url: string; name: string; kind?: string | null; uploaded_at?: string | null };
/** Fechamento com o criador: fica no histórico para sempre ter a informação. */
export type KitDeal = { id?: string; closed_at: string; what: string; amount: number | null; notes?: string | null; closed_by?: string | null };
/** CRM de criadores (migração 000145): onde está a negociação com cada criador nesta marca. */
export type KitStatus = "novo" | "contatado" | "negociando" | "fechado" | "nao_fechou";
export const KIT_STATUS: Record<KitStatus, string> = { novo: "Novo", contatado: "Contatado", negociando: "Em negociação", fechado: "Fechado", nao_fechou: "Não fechou" };
export const KIT_STATUS_COLOR: Record<KitStatus, { bg: string; fg: string }> = {
  novo: { bg: "#eef0f3", fg: "#4b5563" }, contatado: { bg: "#e8f0fb", fg: "#1f4f8f" }, negociando: { bg: "#fdf3e1", fg: "#8a5a00" },
  fechado: { bg: "#e5f4ea", fg: "#1d6b3a" }, nao_fechou: { bg: "#fbe9e9", fg: "#9b2c2c" },
};
export type MediaKit = { creator_id: string; files: KitFile[]; prices: KitPrice[]; email: string | null; phone: string | null; contact: string | null;
  deals: KitDeal[]; notes: string | null; status?: KitStatus; status_note?: string | null; status_at?: string | null; updated_at?: string };
export type MediaKitPayload = Omit<MediaKit, "creator_id" | "updated_at" | "status_at">;
/** O registro salvo como payload (para mudar só o status sem perder o resto). */
export const kitPayload = (kit?: MediaKit): MediaKitPayload => ({ files: kit?.files || [], prices: kit?.prices || [], email: kit?.email || null,
  phone: kit?.phone || null, contact: kit?.contact || null, deals: kit?.deals || [], notes: kit?.notes || null,
  status: kit?.status || (kit?.deals?.length ? "fechado" : "novo"), status_note: kit?.status_note || null });
export const kitStatus = (kit?: MediaKit): KitStatus => kit?.status || (kit?.deals?.length ? "fechado" : "novo");
export const listMediaKits = () => http<{ kits: MediaKit[] }>(path("/media-kits"));
export const saveMediaKit = (creatorId: string, kit: MediaKitPayload) =>
  http<MediaKit>(path(`/${encodeURIComponent(creatorId)}/media-kit`), { method: "PUT", body: JSON.stringify(kit) });
export const KIT_ACCEPT = "application/pdf,image/png,image/jpeg,image/webp";
/** Envia o arquivo direto ao Storage (link assinado) e devolve o link permanente. */
export async function uploadMediaKit(file: File): Promise<KitFile> {
  const type = file.type || "application/pdf";
  const target = await http<{ upload_url: string; public_url: string }>(path("/media-kits/upload"), post({ content_type: type }));
  const response = await fetch(target.upload_url, { method: "PUT", body: file, headers: { "Content-Type": type, "x-upsert": "false" } });
  if (!response.ok) throw new Error("Não foi possível enviar o arquivo.");
  return { url: target.public_url, name: file.name.slice(0, 160), kind: type === "application/pdf" ? "pdf" : "imagem", uploaded_at: new Date().toISOString() };
}
export const brl = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 });

export const kitDateBR = (iso: string) => iso.split("-").reverse().join("/");
/** Resumo de uma linha: "Fechado · Kit ✓ (1) · 3 valor(es) · a partir de R$ 800 · último fechamento 24/11/2026". */
export function kitSummary(kit?: MediaKit): string {
  if (!kit) return "Novo · sem mídia kit";
  const amounts = (kit.prices || []).map((p) => p.amount).filter((a): a is number => a != null);
  return [KIT_STATUS[kitStatus(kit)], kit.files?.length ? `Kit ✓ (${kit.files.length})` : "Sem arquivo",
    amounts.length ? `${kit.prices.length} valor(es) · a partir de ${brl(Math.min(...amounts))}` : "",
    kit.deals?.length ? `último fechamento ${kitDateBR(kit.deals[0].closed_at)}${kit.deals.length > 1 ? ` (${kit.deals.length}x)` : ""}` : ""].filter(Boolean).join(" · ");
}
