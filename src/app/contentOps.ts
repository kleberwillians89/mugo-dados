import { http, clientClientPath } from "./api";

/** Clipping da marca e Redação de campanha — só a equipe Mugô (o backend exige agency_admin). */
const base = (path: string) => clientClientPath(`/studio${path}`);

export type Sentiment = "positivo" | "neutro" | "negativo";
export const SENTIMENT_LABEL: Record<Sentiment, string> = { positivo: "Positiva", neutro: "Neutra", negativo: "Negativa" };
export type Clipping = {
  id: string; url: string; title: string; source: string | null; published_at: string | null; kind: "marca" | "concorrente";
  term: string; sentiment: Sentiment | null; summary: string | null; relevant: boolean | null;
  status: "novo" | "lido" | "arquivado" | "pauta"; calendar_item_id: string | null; created_at: string;
};
export type WeekCount = { total: number; marca: number; concorrente: number } & Record<Sentiment, number>;
export type ClippingSettings = { brand_terms: string[]; competitor_terms: string[]; exclude_terms: string[]; active: boolean; last_run_at: string | null; saved: boolean };
export type ClippingView = { items: Clipping[]; week: { current: WeekCount; previous: WeekCount; marca_variacao: number }; settings: ClippingSettings };

export function getClipping(filters: { kind?: string; sentiment?: string } = {}) {
  const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]).toString();
  return http<ClippingView>(base(`/clipping${q ? `?${q}` : ""}`));
}
export function saveClippingSettings(input: Omit<ClippingSettings, "last_run_at" | "saved">) {
  return http<ClippingSettings>(base("/clipping/settings"), { method: "PUT", body: JSON.stringify(input) });
}
export function refreshClipping() {
  return http<{ found: number; new: number; classified: number }>(base("/clipping/refresh"), { method: "POST", timeoutMs: 120_000 });
}
export function setClippingStatus(id: string, status: "novo" | "lido" | "arquivado") {
  return http<Clipping>(base(`/clipping/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify({ status }) });
}
export function clippingToCalendar(id: string) {
  return http<{ calendar_item_id: string; already: boolean }>(base(`/clipping/${encodeURIComponent(id)}/calendar`), { method: "POST", body: JSON.stringify({}) });
}

export type Channel = "meta_ads" | "google_ads" | "post" | "reels" | "stories" | "whatsapp" | "email";
export const CHANNEL_LABEL: Record<Channel, string> = { meta_ads: "Anúncio Meta", google_ads: "Anúncio Google", post: "Post do feed", reels: "Reels", stories: "Stories", whatsapp: "WhatsApp", email: "E-mail" };
export const CHANNEL_ORDER: Channel[] = ["post", "reels", "stories", "meta_ads", "google_ads", "whatsapp", "email"];
export type LimitCheck = { field: string; index: number | null; length: number; limit: number; over: boolean };
export type Piece = { channel: Channel; label: string; content: unknown; limits: LimitCheck[]; flags: string[]; edited?: boolean };
export type Briefing = { name: string; objective: string; offer: string; audience: string; start: string; end: string; notes: string; channels: Channel[] };
export type Campaign = {
  id: string; name: string; status: "rascunho" | "pronta" | "arquivada"; briefing: Briefing; created_at: string; updated_at: string;
  calendar_item_ids: string[]; package?: { concept: { nome: string; ideia: string; por_que: string }; titles: string[]; pieces: Partial<Record<Channel, Piece>>; generated_at: string };
};

export function listCampaigns() { return http<{ campaigns: Campaign[] }>(base("/campaigns")); }
export function getCampaign(id: string) { return http<{ campaign: Campaign }>(base(`/campaigns/${encodeURIComponent(id)}`)); }
export function createCampaign(briefing: Briefing) {
  return http<{ campaign: Campaign }>(base("/campaigns"), { method: "POST", body: JSON.stringify(briefing), timeoutMs: 150_000 });
}
export function regeneratePiece(id: string, channel: Channel, instruction?: string) {
  return http<{ campaign: Campaign }>(base(`/campaigns/${encodeURIComponent(id)}/pieces/${channel}/regenerate`), { method: "POST", body: JSON.stringify({ instruction: instruction || null }), timeoutMs: 120_000 });
}
export function editPiece(id: string, channel: Channel, content: unknown) {
  return http<{ campaign: Campaign }>(base(`/campaigns/${encodeURIComponent(id)}/pieces/${channel}`), { method: "PUT", body: JSON.stringify({ content }) });
}
export function setCampaignStatus(id: string, status: Campaign["status"]) {
  return http<{ campaign: Campaign }>(base(`/campaigns/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify({ status }) });
}
export function campaignToCalendar(id: string) {
  return http<{ created: number; calendar_item_ids: string[]; already: boolean }>(base(`/campaigns/${encodeURIComponent(id)}/calendar`), { method: "POST" });
}

/** Texto pronto para colar (anúncio, WhatsApp, e-mail), na ordem em que se sobe na plataforma. */
export function pieceText(channel: Channel, content: unknown): string {
  const c = content as Record<string, unknown> | Record<string, unknown>[] | null;
  if (!c) return "";
  const s = (v: unknown) => String(v ?? "");
  if (channel === "meta_ads" && Array.isArray(c)) return c.map((ad, i) => `Anúncio ${i + 1}\nTexto principal: ${s(ad.texto_principal)}\nTítulo: ${s(ad.titulo)}\nDescrição: ${s(ad.descricao)}\nBotão: ${s(ad.cta)}`).join("\n\n");
  if (channel === "google_ads" && !Array.isArray(c)) return `Títulos:\n${((c.titulos as string[]) || []).join("\n")}\n\nDescrições:\n${((c.descricoes as string[]) || []).join("\n")}`;
  if (channel === "post" && !Array.isArray(c)) return [s(c.legenda), s(c.cta)].filter(Boolean).join("\n\n");
  if (channel === "reels" && !Array.isArray(c)) return [`Gancho: ${s(c.gancho)}`, `Capa: ${s(c.texto_capa)}`, ...((c.cenas as Record<string, unknown>[]) || []).map((x) => `[${s(x.segundos)}] ${s(x.visual)} | Tela: ${s(x.texto_tela)} | Narração: ${s(x.narracao)}`), `CTA: ${s(c.cta)}`].join("\n");
  if (channel === "stories" && Array.isArray(c)) return c.map((x) => `Quadro ${s(x.quadro)}: ${s(x.texto)} (${s(x.visual)}; ação: ${s(x.acao)})`).join("\n");
  if (channel === "whatsapp" && !Array.isArray(c)) return s(c.mensagem);
  if (channel === "email" && !Array.isArray(c)) return `Assunto: ${s(c.assunto)}\nPré-cabeçalho: ${s(c.preheader)}\n\n${s(c.corpo)}`;
  return JSON.stringify(c, null, 2);
}
