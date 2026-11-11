import type { StudioBriefing } from "./studio";
import { http, clientClientPath } from "./api";
import type { GuardIssue, StudioFormat } from "./studio";

/** Clipping da marca (só a equipe Mugô) e Social Media: Redação de campanha + Matriz de conteúdo
 * (módulo social_media, que a Mugô libera por usuário; o backend confere cada chamada). */
const base = (path: string) => clientClientPath(`/studio${path}`);

export type Sentiment = "positivo" | "neutro" | "negativo" | "misto";
export const SENTIMENT_LABEL: Record<Sentiment, string> = { positivo: "Positiva", neutro: "Neutra", negativo: "Negativa", misto: "Mista" };
export type Criticality = "baixa" | "media" | "alta" | "critica";
export const CRITICALITY_LABEL: Record<Criticality, string> = { baixa: "Baixa", media: "Média", alta: "Alta", critica: "Crítica" };
export const KIND_LABEL: Record<string, string> = { marca: "Marca", concorrente: "Concorrente", pessoa: "Pessoa", tema: "Tema" };
export type Clipping = {
  id: string; url: string; title: string; source: string | null; published_at: string | null; kind: "marca" | "concorrente" | "pessoa" | "tema";
  term: string; sentiment: Sentiment | null; summary: string | null; relevant: boolean | null;
  status: "novo" | "lido" | "arquivado" | "pauta"; calendar_item_id: string | null; created_at: string;
  relevance?: number | null; criticality?: Criticality | null; main_theme?: string | null; entities?: string[];
  opportunities?: string[]; risks?: string[]; justification?: string | null; evidence?: string[]; alert_status?: string;
};
export type Count = { key: string; count: number };
export type ClippingInsights = {
  total: number; analyzed: number; sentiment: Count[]; themes: Count[]; sources: Count[]; mentions: Count[];
  timeline: { day: string; count: number }[]; critical: (Pick<Clipping, "id" | "title" | "url" | "source" | "published_at" | "criticality" | "relevance" | "sentiment" | "risks">)[];
};
export type ReportRef = { text: string; url: string };
export type ClippingReport = {
  period: string; focus: string; items: number; summary: string; highlights: ReportRef[]; risks: ReportRef[]; opportunities: ReportRef[];
  sources: { title: string; url: string; source: string | null }[]; ai?: boolean;
};
export const RADAR_FIELDS = [
  ["brand_terms", "Marca e variações"], ["competitor_terms", "Concorrentes"], ["people", "Pessoas e porta-vozes"],
  ["keywords", "Palavras-chave"], ["themes", "Temas estratégicos"], ["exclude_terms", "Ignorar notícias que tenham"],
] as const;
export type WeekCount = { total: number; marca: number; concorrente: number } & Record<Sentiment, number>;
export type ClippingSettings = {
  brand_terms: string[]; competitor_terms: string[]; exclude_terms: string[]; active: boolean; last_run_at: string | null; saved: boolean;
  people?: string[]; keywords?: string[]; themes?: string[]; feeds?: string[]; region?: string | null; relevance_criteria?: string | null;
  min_relevance?: number;
};
export type ClippingView = { items: Clipping[]; week: { current: WeekCount; previous: WeekCount; marca_variacao: number }; settings: ClippingSettings };

export function getClipping(filters: { kind?: string; sentiment?: string; q?: string; theme?: string; min_relevance?: string; criticality?: string } = {}) {
  const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]).toString();
  return http<ClippingView>(base(`/clipping${q ? `?${q}` : ""}`));
}
export function getClippingInsights(days = 30) {
  return http<ClippingInsights>(base(`/clipping/insights?days=${days}`));
}
export function getClippingReport(period: "diario" | "semanal" | "mensal", focus: "cobertura" | "concorrentes" | "setor" | "riscos") {
  return http<ClippingReport>(base("/clipping/report"), { method: "POST", body: JSON.stringify({ period, focus }), timeoutMs: 90_000 });
}
export function exportClipping(days = 30) {
  return http<Blob>(base(`/clipping/export?days=${days}`), { responseType: "blob" });
}
export function saveClippingSettings(input: Omit<ClippingSettings, "last_run_at" | "saved">) {
  return http<ClippingSettings>(base("/clipping/settings"), { method: "PUT", body: JSON.stringify(input) });
}
export type RadarSuggestion = Record<(typeof RADAR_FIELDS)[number][0], string[]> & { region: string; relevance_criteria: string };
/** Rascunho do radar pela IA; nada é gravado. */
export function suggestClippingSettings() {
  return http<RadarSuggestion>(base("/clipping/settings/suggest"), { method: "POST", timeoutMs: 90_000 });
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
export type Piece = { channel: Channel; label: string; content: unknown; limits: LimitCheck[]; flags: string[]; guard?: GuardIssue[]; edited?: boolean };
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

/* ------------------------------------------------------------------ Matriz de conteúdo (Social Media) */

export type Platform = "instagram" | "facebook" | "tiktok" | "linkedin" | "youtube" | "pinterest";
export const PLATFORM_LABEL: Record<Platform, string> = { instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", linkedin: "LinkedIn", youtube: "YouTube", pinterest: "Pinterest" };
export const PLATFORM_ORDER: Platform[] = ["instagram", "tiktok", "facebook", "linkedin", "youtube", "pinterest"];
/** Formatos de cada plataforma (mesma regra do backend: studio_matrix.PLATFORM_FORMATS). */
export const PLATFORM_FORMATS: Record<Platform, StudioFormat[]> = {
  instagram: ["reels", "carrossel", "imagem", "stories"], facebook: ["imagem", "video", "carrossel", "stories"],
  tiktok: ["video"], linkedin: ["imagem", "carrossel", "video"], youtube: ["video"],
  pinterest: ["imagem", "carrossel", "video"],
};
export const WEEKDAY_LABEL = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"];
export type OpportunityStatus = "sugerida" | "selecionada" | "descartada" | "exportada";
export type Opportunity = {
  id: string; matrix_id: string; platform: Platform; pillar: string; week: number; weekday: number; format: StudioFormat;
  title: string; hook: string | null; angle: string | null; caption_draft: string | null; rationale: string | null;
  /** Conteúdo criado na Matriz: roteiro (cenas, slides ou telas) e direção da arte. */
  script?: string | null; visual_idea?: string | null;
  /** Briefing da peça (Atendimento do iAgência), criado junto com o conteúdo; vai para a pauta na exportação. */
  briefing?: StudioBriefing | null;
  guard?: { type: string; text: string; fix: string }[]; status: OpportunityStatus; edited: boolean; position: number; calendar_item_id: string | null; updated_at?: string;
};
export type MatrixSummary = { id: string; week_start: string; platforms: Platform[]; pillars: { name: string; weight?: number }[];
  focus: string | null; summary: string | null; status: string; created_at: string };
export type ContentMatrix = MatrixSummary & { notes?: string[]; opportunities: Opportunity[] };
export type MatrixRequest = { week_start: string; platforms: Platform[]; pillars: string[]; per_week: number; focus: string };
export type OpportunityPatch = Partial<Pick<Opportunity, "platform" | "pillar" | "week" | "weekday" | "format" | "title" | "hook" | "angle" | "caption_draft" | "rationale" | "script" | "visual_idea">> & { status?: Exclude<OpportunityStatus, "exportada"> };
export type OpportunityCreate = Pick<Opportunity, "platform" | "pillar" | "week" | "weekday" | "format" | "title" | "hook" | "angle" | "caption_draft" | "rationale"> & Partial<Pick<Opportunity, "script" | "visual_idea">>;

const mx = (path = "") => base(`/matrix${path}`);
export function listMatrices() { return http<{ matrices: MatrixSummary[] }>(mx()); }
export function getMatrix(id: string) { return http<{ matrix: ContentMatrix }>(mx(`/${encodeURIComponent(id)}`)); }
export function createMatrix() {
  return http<{ matrix: ContentMatrix }>(mx(), { method: "POST", body: JSON.stringify({}), timeoutMs: 180_000 });
}
export function archiveMatrix(id: string) { return http<{ matrix: MatrixSummary }>(mx(`/${encodeURIComponent(id)}`), { method: "DELETE" }); }
export function updateOpportunity(matrixId: string, id: string, patch: OpportunityPatch) {
  return http<{ opportunity: Opportunity }>(mx(`/${encodeURIComponent(matrixId)}/opportunities/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(patch) });
}
export function addOpportunity(matrixId: string, input: OpportunityCreate) {
  return http<{ opportunity: Opportunity }>(mx(`/${encodeURIComponent(matrixId)}/opportunities`), { method: "POST", body: JSON.stringify(input) });
}
export function deleteOpportunity(matrixId: string, id: string) {
  return http<{ opportunity: Opportunity }>(mx(`/${encodeURIComponent(matrixId)}/opportunities/${encodeURIComponent(id)}`), { method: "DELETE" });
}
export function refineOpportunity(matrixId: string, id: string, instruction?: string) {
  return http<{ opportunity: Opportunity }>(mx(`/${encodeURIComponent(matrixId)}/opportunities/${encodeURIComponent(id)}/refine`),
    { method: "POST", body: JSON.stringify({ instruction: instruction || null }), timeoutMs: 120_000 });
}
/** A IA cria o conteúdo da pauta: gancho, legenda, roteiro e ideia de imagem. */
export function createOpportunityContent(matrixId: string, id: string, instruction?: string) {
  return http<{ opportunity: Opportunity }>(mx(`/${encodeURIComponent(matrixId)}/opportunities/${encodeURIComponent(id)}/content`),
    { method: "POST", body: JSON.stringify({ instruction: instruction || null }), timeoutMs: 120_000 });
}
export function setOpportunitiesStatus(matrixId: string, ids: string[], status: Exclude<OpportunityStatus, "exportada">) {
  return http<{ updated: number; matrix: ContentMatrix }>(mx(`/${encodeURIComponent(matrixId)}/status`), { method: "POST", body: JSON.stringify({ ids, status }) });
}
export function matrixToCalendar(matrixId: string, ids?: string[]) {
  return http<{ created: number; already: number; calendar_item_ids: string[]; matrix: ContentMatrix }>(
    mx(`/${encodeURIComponent(matrixId)}/calendar`), { method: "POST", body: JSON.stringify(ids?.length ? { ids } : {}), timeoutMs: 120_000 });
}

/* ------------------------------------------------------------------ Redação (editor de texto da marca) */

export type DocKind = "livre" | "post" | "legenda" | "roteiro" | "artigo" | "email" | "release" | "campanha";
export const DOC_KIND_LABEL: Record<DocKind, string> = { livre: "Texto livre", post: "Post", legenda: "Legenda", roteiro: "Roteiro de vídeo",
  artigo: "Artigo / blog", email: "E-mail", release: "Release", campanha: "Texto de campanha" };
export type DocSummary = { id: string; title: string; kind: DocKind; status: string; calendar_item_id: string | null; updated_at: string; created_at: string; excerpt?: string };
export type StudioDocument = DocSummary & { content_html: string; content_text: string };
export type DocAIAction = "escrever" | "continuar" | "reescrever" | "encurtar" | "expandir" | "corrigir" | "titulos";
export type DocAIResult = { action: DocAIAction; text: string; titles: string[]; flags: string[]; guard: { type: string; text: string; fix: string }[] };

const docs = (path = "") => base(`/documents${path}`);
export function listDocuments() { return http<{ documents: DocSummary[] }>(docs()); }
export function getDocument(id: string) { return http<{ document: StudioDocument }>(docs(`/${encodeURIComponent(id)}`)); }
export function createDocument(input: { title?: string; kind?: DocKind; content_html?: string }) {
  return http<{ document: StudioDocument }>(docs(), { method: "POST", body: JSON.stringify(input) });
}
export function saveDocument(id: string, patch: Partial<Pick<StudioDocument, "title" | "kind" | "content_html" | "status">>) {
  return http<{ document: StudioDocument }>(docs(`/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(patch) });
}
export function documentAI(input: { action: DocAIAction; kind: DocKind; title?: string; instruction?: string; selection?: string; document_text?: string }) {
  return http<DocAIResult>(docs("/ai"), { method: "POST", body: JSON.stringify(input), timeoutMs: 150_000 });
}
export function documentToCalendar(id: string, input: { scheduled_at?: string; channel: Platform; format: StudioFormat }) {
  return http<{ calendar_item_id: string; created: boolean; updated: boolean }>(docs(`/${encodeURIComponent(id)}/calendar`), { method: "POST", body: JSON.stringify(input) });
}
