import { http, clientClientPath, publicHttp } from "./api";

export const STUDIO_FORMATS = { reels: "Reels", carrossel: "Carrossel", imagem: "Imagem", stories: "Stories", video: "Vídeo" } as const;
export type StudioFormat = keyof typeof STUDIO_FORMATS;
/** Plataformas do Calendário. Só o Instagram publica sozinho; nas outras a equipe publica à mão. */
export const STUDIO_CHANNELS = { instagram: "Instagram", tiktok: "TikTok", facebook: "Facebook", linkedin: "LinkedIn", youtube: "YouTube", pinterest: "Pinterest" } as const;
export type StudioChannel = keyof typeof STUDIO_CHANNELS;
/** Evento da janela disparado quando o Perfil da marca é salvo (detail = perfil novo). */
export const BRAND_PROFILE_SAVED = "mugo:brand-profile-saved";
export const AUTO_PUBLISH_CHANNELS: StudioChannel[] = ["instagram"];
export const STUDIO_STATUS = { rascunho: "Rascunho", em_revisao: "Em revisão", aprovado: "Aprovado", rejeitado: "Ajuste pedido", publicado: "Publicado" } as const;
export type StudioStatus = keyof typeof STUDIO_STATUS;

export type BrandPillar = { name: string; weight: number; description: string };
export type BrandProfile = {
  tone_of_voice: string; personality: string; audience: string; pillars: BrandPillar[];
  keywords_use: string[]; keywords_avoid: string[]; hashtags: string[]; restrictions: string;
  /** Cores, composição, estilo de foto e de arte (a IA tira das imagens dos posts mais curtidos). */
  visual_identity?: string;
  posts_per_week: number; editorial_platforms?: StudioChannel[]; posts_per_week_by_platform?: Partial<Record<StudioChannel, number>>;
  formats_enabled: StudioFormat[]; custom_dates: { date: string; label: string }[];
  /** Idioma do que vai ao ar (legendas, roteiros, hashtags, respostas de comentário). Pautas e notas seguem em português. */
  content_language?: ContentLanguage;
};
export const CONTENT_LANGUAGES = { "pt-BR": "Português (Brasil)", en: "Inglês", es: "Espanhol" } as const;
export type ContentLanguage = keyof typeof CONTENT_LANGUAGES;

export type CalendarSignals = {
  basis?: { reason?: string; hours?: string; weekday_reach_index?: number | null; slot_reach_index?: number | null; confidence?: string | null };
  seasonal?: string | null;
  trend?: { topic: string; source_url: string; researched_at: string };
  palavras_evitar_encontradas?: string[];
  /** Trava de fidelidade: oferta, número ou urgência que não está no perfil nem nas campanhas. */
  fora_da_marca?: GuardIssue[];
};

export type CalendarItem = {
  id: string; client_id: string; month: string; scheduled_at: string; format: StudioFormat;
  /** Plataforma (padrão Instagram). */
  channel?: StudioChannel;
  pillar: string | null; title: string; hook: string | null; caption_draft: string | null; rationale: string | null;
  signals: CalendarSignals; status: StudioStatus; review_note: string | null; origin: "ia" | "manual" | "importado" | "matriz";
  /** Link da arte (Canva/Google Drive). */
  art_url?: string | null;
  /** Conteúdo criado na Matriz: roteiro e direção da arte (referência para produzir a peça). */
  script?: string | null; visual_idea?: string | null;
  /** @ dos colaboradores no Instagram (até 3; sem @). */
  collaborators?: string[];
  /** Produtos da loja do Instagram marcados no post (publicados junto). */
  product_tags?: ProductTag[];
  /** Equipe validou o agendamento depois da aprovação do cliente. */
  schedule_confirmed_at?: string | null;
  /** Publicação automática no Instagram (job a cada 5 min no horário do post). */
  publish_status?: "publicando" | "publicado" | "falhou" | "simulado" | "manual" | null;
  publish_error?: string | null;
  published_permalink?: string | null;
  reviewed_by: string | null; reviewed_at: string | null; updated_at?: string;
  /** O cliente editou pelo painel; a equipe confere (tarefa no CRM). */
  client_edited_at?: string | null; client_edited_fields?: string[];
  /** Arte anexada, na ordem dos slides; URLs assinadas de curta duração. */
  /** Impulsionamento previsto no plano do Mídia On salvo para o mês (só na tela). */
  boost?: { start: string; end: string; budget: number; why: string };
};

export type ItemPatch = Partial<Pick<CalendarItem, "scheduled_at" | "channel" | "format" | "pillar" | "title" | "hook" | "caption_draft" | "rationale" | "status" | "review_note" | "art_url" | "collaborators" | "product_tags">>;

/** Importar calendário pronto (PowerPoint/texto): a IA organiza, a equipe revisa e confirma. */
export type ImportRow = { slide?: number; date: string; time: string; format: StudioFormat; title: string; caption: string; art_url: string; issues?: string[] };
export function parseCalendarImport(slides: { index: number; text: string; links: string[] }[], fileName: string) {
  return http<{ items: ImportRow[]; notes: string[]; slides: number }>(base("/calendar/import/parse"), { method: "POST", body: JSON.stringify({ slides, file_name: fileName }), timeoutMs: 180_000 });
}
export function commitCalendarImport(items: ImportRow[], approved: boolean) {
  const rows = items.map(({ date, time, format, title, caption, art_url }) => ({ date, time, format, title, caption, art_url }));
  return http<{ created: number; skipped_duplicates: number; invalid: number; months: string[]; approved: boolean }>(base("/calendar/import/commit"), { method: "POST", body: JSON.stringify({ items: rows, approved }) });
}

const base = (path: string) => clientClientPath(`/studio${path}`);

export function getBrandProfile(): Promise<{ profile: BrandProfile; saved: boolean; updated_at?: string | null }> {
  return http(base("/brand-profile"));
}
export function saveBrandProfile(profile: BrandProfile) {
  return http<{ profile: BrandProfile }>(base("/brand-profile"), { method: "PUT", body: JSON.stringify(profile) });
}
export function getCalendar(month: string): Promise<{ month: string; items: CalendarItem[] }> {
  return http(base(`/calendar?month=${encodeURIComponent(month)}`));
}
export function generateCalendar(month: string): Promise<{ created: number; kept: number; items: CalendarItem[]; observacoes: string[] }> {
  // Gera com IA: pode levar mais que o timeout padrão de leitura.
  return http(base("/calendar/generate"), { method: "POST", body: JSON.stringify({ month }), timeoutMs: 150_000 });
}
export function updateCalendarItem(id: string, patch: ItemPatch) {
  return http<{ item: CalendarItem }>(base(`/calendar/items/${encodeURIComponent(id)}`), { method: "PATCH", body: JSON.stringify(patch) });
}
/** Aprovar ou pedir ajuste (comentário obrigatório no ajuste). Vale para quem só vê o Calendário, como o link de aprovação. */
export function decideCalendarItem(id: string, status: "aprovado" | "rejeitado", reviewNote?: string) {
  return http<{ item: CalendarItem }>(base(`/calendar/items/${encodeURIComponent(id)}/decision`), { method: "POST",
    body: JSON.stringify({ status, ...(reviewNote ? { review_note: reviewNote } : {}) }) });
}
// ---------------------------------------------------------------- produtos da loja (Instagram Shopping)
/** Produto marcado: slide = arte do carrossel (0 = primeira); x/y de 0.01 a 1 a partir do canto de cima (só imagem). */
export type ProductTag = { product_id: string; name?: string | null; image_url?: string | null; slide: number; x: number; y: number };
export type ShopStatus = { ready: boolean; eligible: boolean | null; catalogs: { id: string; name: string | null; shop_name: string | null; product_count: number | null }[];
  missing_scopes: string[]; message: string | null };
export type ShopProduct = { product_id: string; name: string; image_url: string | null; sku: string | null; review_status: string | null;
  variants: { product_id: string; name: string | null }[] };
export function getShop() { return http<ShopStatus>(base("/calendar/shop"), { timeoutMs: 30_000 }); }
export function searchShopProducts(q: string, catalogId?: string) {
  const params = new URLSearchParams({ q, ...(catalogId ? { catalog_id: catalogId } : {}) });
  return http<{ products: ShopProduct[] }>(base(`/calendar/shop/products?${params.toString()}`), { timeoutMs: 30_000 });
}

export function createCalendarItem(item: Required<Pick<CalendarItem, "scheduled_at" | "format" | "title">> & ItemPatch) {
  return http<{ item: CalendarItem }>(base("/calendar/items"), { method: "POST", body: JSON.stringify(item) });
}
export function deleteCalendarItem(id: string) {
  return http(base(`/calendar/items/${encodeURIComponent(id)}`), { method: "DELETE" });
}

const SP = "America/Sao_Paulo";
export function localParts(iso: string) {
  const d = new Date(iso);
  const date = new Intl.DateTimeFormat("en-CA", { timeZone: SP, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const time = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, hour: "2-digit", minute: "2-digit", hour12: false }).format(d);
  const weekday = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, weekday: "long" }).format(d);
  const label = new Intl.DateTimeFormat("pt-BR", { timeZone: SP, day: "2-digit", month: "short" }).format(d);
  return { date, time, weekday, label };
}
/** "2026-11-03" + "19:00" no fuso de São Paulo (UTC-3, sem horário de verão). */
export function toSaoPauloIso(date: string, time: string) {
  return `${date}T${time}:00-03:00`;
}
export function nextMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
export const listToText = (values: string[] | undefined) => (values || []).join(", ");
export const textToList = (value: string) => value.split(/[,\n]/).map((v) => v.trim()).filter(Boolean);

// ------------------------------------------------------------ aprovação do cliente
export type ApprovalRequest = { id: string; month: string; items: number; contact_name: string | null; status: "aberto" | "concluido" | "cancelado" | "expirado"; expires_at: string; created_at: string; completed_at: string | null; last_reminded_at?: string | null };
export type ApprovalCreated = { request_id: string; link: string; expires_at: string; whatsapp_text: string; whatsapp_url: string; whatsapp?: MessageResult | { status: "falhou"; detail: string };
  /** Cópia para a equipe Mugô (mesma mensagem e mesmo link). */
  team?: { name: string; status: string; error?: string }[] };
export function listApprovals(): Promise<{ requests: ApprovalRequest[] }> { return http(base("/approvals")); }
export function sendForApproval(input: { month: string; item_ids: string[]; contact_name?: string; contact_phone?: string; message?: string; contact_id?: string; send_whatsapp?: boolean; notify_team?: boolean }) {
  return http<ApprovalCreated>(base("/approvals"), { method: "POST", body: JSON.stringify(input) });
}
/** now=true: publica agora (o job dos próximos 5 minutos publica). */
export function confirmSchedule(itemId: string, now = false) {
  return http<{ ok: boolean; item: CalendarItem }>(base(`/calendar/items/${encodeURIComponent(itemId)}/schedule`), { method: "POST", body: JSON.stringify({ now }) });
}
export function retryPublish(itemId: string) {
  return http<{ ok: boolean; item: CalendarItem }>(base(`/calendar/items/${encodeURIComponent(itemId)}/publish/retry`), { method: "POST" });
}
export function cancelApproval(id: string) { return http(base(`/approvals/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export type PublicApprovalItem = Pick<CalendarItem, "id" | "scheduled_at" | "format" | "pillar" | "title" | "hook" | "caption_draft" | "art_url"> & { decision: "aprovado" | "ajuste_solicitado" | null; comment: string | null };
export type PublicApproval = { client_name: string; month: string; contact_name: string | null; status: string; expires_at: string; items: PublicApprovalItem[] };
export function getPublicApproval(token: string) { return publicHttp<PublicApproval>(`/api/public/approvals/${encodeURIComponent(token)}`); }
export function decidePublicApproval(token: string, itemId: string, body: { action: "aprovado" | "ajuste_solicitado"; comment?: string; reviewer_name?: string }) {
  return publicHttp<{ ok: boolean }>(`/api/public/approvals/${encodeURIComponent(token)}/items/${encodeURIComponent(itemId)}`, { method: "POST", body: JSON.stringify(body) });
}

// ------------------------------------------------------------ inteligência e motores de conteúdo
export type BasedOn = { kpis: number; campanhas: number; posts_analisados: number; metas: number; aprovados: number; ajustes: number; lacunas: string[] };
export const GAP_LABELS: Record<string, string> = {
  perfil_da_marca_vazio: "perfil da marca vazio", contexto_do_negocio_vazio: "contexto do negócio vazio", sem_kpis_no_periodo: "sem KPIs no período",
  sem_historico_de_posts: "sem histórico de posts", sem_metas_no_mes: "sem metas no mês", kpis_e_campanhas: "KPIs indisponíveis agora",
  posts_instagram: "posts indisponíveis agora", melhores_horarios: "horários indisponíveis agora", metas: "metas indisponíveis agora",
  ultima_analise: "análise indisponível agora", aprendizados_de_aprovacao: "aprendizados indisponíveis agora",
  perfil_da_marca: "perfil indisponível agora", contexto_do_negocio: "contexto indisponível agora",
};
export function sourcesText(s?: ProfileSources | null): string {
  if (!s) return "";
  const parts = [s.posts ? `${s.posts} posts de 12 meses` : "", s.imagens ? `${s.imagens} imagem(ns) analisada(s)` : "",
    s.aprovados ? `${s.aprovados} aprovação(ões)` : "", s.ajustes ? `${s.ajustes} ajuste(s) pedido(s)` : "",
    s.comentarios ? `${s.comentarios} comentário(s) do cliente` : "", s.reescritas ? `${s.reescritas} texto(s) reescrito(s) pelo cliente` : "",
    s.midia_on ? "plano da Mídia On" : ""].filter(Boolean);
  return parts.length ? `Leu ${parts.join(", ")}.` : "";
}

export function basedOnText(b?: BasedOn | null): string {
  if (!b) return "";
  const parts = [b.posts_analisados ? `${b.posts_analisados} posts analisados` : "", b.aprovados ? `${b.aprovados} pauta(s) aprovada(s)` : "",
    b.ajustes ? `${b.ajustes} ajuste(s) pedido(s)` : "", b.campanhas ? `${b.campanhas} campanha(s)` : "", b.kpis ? `${b.kpis} KPI(s)` : "",
    b.metas ? `${b.metas} meta(s)` : ""].filter(Boolean);
  return parts.length ? `Com base em ${parts.join(", ")}.` : "Sem dados suficientes da conta: a IA usou só o perfil e a pauta.";
}

export const ASSIST_ACTIONS = { legenda: "Legenda final", variacoes: "3 variações", ganchos: "5 ganchos", hashtags: "Hashtags", roteiro_reels: "Roteiro de Reels", revisar: "Revisar" } as const;
export type AssistAction = keyof typeof ASSIST_ACTIONS;
export type AssistResult =
  | { action: "legenda"; result: { caption: string; cta: string; why: string } }
  | { action: "variacoes"; result: { variations: { angle: string; caption: string }[]; recommended_index: number; why: string } }
  | { action: "ganchos"; result: { hooks: { hook: string; angle: string }[] } }
  | { action: "hashtags"; result: { hashtags: string[]; why: string } }
  | { action: "roteiro_reels"; result: { duration_seconds: number; cover_text: string; audio_suggestion: string; scenes: { seconds: string; visual: string; text_on_screen: string; voiceover: string }[] } }
  | { action: "revisar"; result: { issues: { problem: string; fix: string }[]; improved_caption: string } };
export type AssistResponse = AssistResult & { flags: string[]; guard?: GuardIssue[]; based_on: BasedOn };
export function runAssist(action: AssistAction, item: { format: StudioFormat; title: string; pillar?: string; hook?: string; caption_draft?: string; scheduled_at?: string }, instruction?: string, itemId?: string) {
  return http<AssistResponse>(base("/assist"), { method: "POST", body: JSON.stringify({ action, item, instruction: instruction || undefined, item_id: itemId || undefined }), timeoutMs: 100_000 });
}
export type ChatTurn = { role: "user" | "assistant"; content: string };
export function strategyChat(month: string, messages: ChatTurn[]) {
  return http<{ reply: string; suggested_actions: string[]; based_on: BasedOn }>(base("/strategy/chat"), { method: "POST", body: JSON.stringify({ month, messages }), timeoutMs: 100_000 });
}
/** Fontes que a IA avançada leu para sugerir o perfil (12 meses). */
export type ProfileSources = { posts: number; imagens: number; aprovados: number; ajustes: number; comentarios: number; reescritas: number; midia_on: number };
export type ProfileReason = { campo: string; motivo: string };
export type ProfileSuggestionResult = { profile: BrandProfile; notes: string[]; reasons?: ProfileReason[]; based_on: BasedOn; sources?: ProfileSources; gaps?: string[] };
export function suggestBrandProfile() {
  return http<ProfileSuggestionResult>(base("/brand-profile/suggest"), { method: "POST", body: JSON.stringify({}), timeoutMs: 180_000 });
}
/** Sugestão mensal (job do dia 1) esperando revisão da equipe. */
export type PendingProfileSuggestion = { id: string; month: string; created_at: string; suggestion: ProfileSuggestionResult };
export function getProfileSuggestion() {
  return http<{ suggestion: PendingProfileSuggestion | null }>(base("/brand-profile/suggestion"));
}
export function resolveProfileSuggestion(id: string, status: "aplicada" | "descartada") {
  return http<{ ok: true }>(base(`/brand-profile/suggestion/${encodeURIComponent(id)}`), { method: "POST", body: JSON.stringify({ status }) });
}

// ------------------------------------------------------------ aprovação: funil, contatos e mensagens
export const STAGES = { rascunho: "Rascunho", revisao_interna: "Revisão interna", com_cliente: "Com o cliente", ajuste: "Ajuste pedido", aprovado: "Aprovado", publicado: "Publicado" } as const;
export type Stage = keyof typeof STAGES;
/** Status gravado quando a pauta é arrastada para a coluna; "com o cliente" só via envio do link. */
export const STAGE_STATUS: Partial<Record<Stage, StudioStatus>> = { rascunho: "rascunho", revisao_interna: "em_revisao", ajuste: "rejeitado", aprovado: "aprovado", publicado: "publicado" };
export type PipelineItem = CalendarItem & { stage: Stage; request: { request_id: string; sent_at: string; contact_name: string | null; expires_at: string; last_reminded_at: string | null } | null;
  client_feedback: { action: "aprovado" | "ajuste_solicitado"; comment: string | null; reviewer_name: string | null; created_at: string } | null };
export function getPipeline(month: string) {
  return http<{ month: string; stages: Stage[]; counts: Record<Stage, number>; items: PipelineItem[] }>(base(`/approvals/pipeline?month=${encodeURIComponent(month)}`));
}

export const RECEIVES = { conteudo: "Conteúdo", trafego: "Tráfego pago", resultados: "Resultados do mês" } as const;
export type Receives = keyof typeof RECEIVES;
export type ClientContact = { id: string; name: string; phone: string; role: string | null; receives: Receives[]; is_primary: boolean };
export type ContactInput = { name: string; phone: string; role?: string; receives: Receives[]; is_primary: boolean };
export type WhatsappChannel = "mugozap" | "wa_link" | "nao_configurado";
export function listContacts() { return http<{ contacts: ClientContact[]; whatsapp_channel: WhatsappChannel; whatsapp_missing?: string[] }>(base("/contacts")); }
export function createContact(input: ContactInput) { return http<{ contact: ClientContact }>(base("/contacts"), { method: "POST", body: JSON.stringify(input) }); }
export function updateContact(id: string, input: ContactInput) { return http<{ contact: ClientContact }>(base(`/contacts/${encodeURIComponent(id)}`), { method: "PUT", body: JSON.stringify(input) }); }
export function deleteContact(id: string) { return http(base(`/contacts/${encodeURIComponent(id)}`), { method: "DELETE" }); }

export const MESSAGE_KINDS = { aprovacao: "Pautas para aprovar", lembrete: "Lembrete de aprovação", agenda: "Agenda da semana", trafego: "Relatório de tráfego (7 dias)", resultados: "Resultados do mês", semanal: "Resumo semanal (sexta)", convite: "Perguntar se quer o resumo" } as const;
export type MessageKind = keyof typeof MESSAGE_KINDS;
export type MessagePreview = { kind: MessageKind; template_name: string; params: Record<string, string>; text: string; editable: string[];
  contact: { id: string; name: string; role: string | null }; phone_masked: string; header_image: string | null; channel: WhatsappChannel };
export type MessageResult = { status: "enviado" | "link_gerado" | "aguardando"; channel: "mugozap" | "wa_link"; whatsapp_url?: string; text: string; already_sent?: boolean };
export type MessageLog = { id: string; contact_name: string | null; phone_masked: string | null; kind: MessageKind; template_name: string | null; channel: string; status: string; error_code: string | null; preview: { text?: string }; created_at: string;
  provider_message_id?: string | null; request_id?: string | null; delivery_status?: "accepted" | "sent" | "delivered" | "read" | "failed" | null };
type MessageInput = { kind: MessageKind; contact_id?: string; request_id?: string; overrides?: Record<string, string> };
export function previewMessage(input: MessageInput) { return http<MessagePreview>(base("/messages/preview"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function sendMessage(input: MessageInput) { return http<MessageResult>(base("/messages/send"), { method: "POST", body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function listMessages(requestId?: string) {
  return http<{ messages: MessageLog[]; templates: string[]; whatsapp_channel: WhatsappChannel; whatsapp_missing?: string[] }>(base(`/messages${requestId ? `?request_id=${encodeURIComponent(requestId)}` : ""}`));
}

/** Problema apontado pela trava de fidelidade à marca (o texto não é reescrito; a equipe decide). */
export type GuardIssue = { type: "palavra_proibida" | "promessa_sem_dado" | "urgencia_inventada"; text: string; fix: string };

/** Central da marca: o mês numa página (cada bloco pode vir null se a fonte falhar). */
export type CentralAlert = { level: "atencao" | "info"; module: string; text: string };
export type CentralView = {
  month: string; agency: boolean;
  numbers: { start: string; end: string | null; investimento?: number | null; faturamento?: number | null; pedidos?: number | null; retorno?: number | null;
    vendas_midia_paga?: number | null; melhor_campanha?: { campanha: string; pedidos: number; vendas: number } | null } | null;
  calendar: { total: number; counts: Record<string, number>; waiting_client: number; off_brand: { id: string; title: string; issues: number }[];
    upcoming: { id: string; title: string; format: StudioFormat; scheduled_at: string; stage: string; pillar: string | null }[] } | null;
  media: { objetivo: string | null; verba: number | null; elapsed_days: number; days_in_month: number;
    channels: { channel: string; label: string; planned_spend: number | null; spent: number; expected_to_date: number | null; projected_spend: number; pace: number | null; roas: number | null; cpa: number | null }[] } | null;
  clipping: { week: { current: Record<string, number>; previous: Record<string, number>; marca_variacao: number };
    latest: { id: string; title: string; source: string | null; url: string; kind: string; sentiment: string | null }[] } | null;
  tasks: { available: boolean; reason?: string; open?: number; late?: number; next?: { title: string; due_date: string | null; status: string }[] } | null;
  campaigns?: { id: string; name: string; status: string; objective: string | null; start: string | null; end: string | null; posts_no_calendario: number }[] | null;
  alerts: CentralAlert[];
};
export function getCentral(month: string) { return http<CentralView>(base(`/central?month=${encodeURIComponent(month)}`), { timeoutMs: 60_000 }); }
/** Comentários num post (cliente e equipe Mugô no mesmo fio). */
export type ItemComment = { id: string; author_side: "cliente" | "mugo"; author_name: string | null; body: string; created_at: string };
export function listItemComments(itemId: string) { return http<{ comments: ItemComment[] }>(base(`/calendar/items/${encodeURIComponent(itemId)}/comments`)); }
export function addItemComment(itemId: string, body: string) { return http<{ ok: true; comment: ItemComment }>(base(`/calendar/items/${encodeURIComponent(itemId)}/comments`), { method: "POST", body: JSON.stringify({ body }) }); }

// ---------------------------------------------------------------- referências da marca
export type BrandReference = { id: string; url: string; kind: "link" | "arte"; note: string | null; author_side: "cliente" | "mugo"; created_at: string; can_delete: boolean };
export function listReferences() { return http<{ references: BrandReference[] }>(base("/references")); }
export function addReference(input: { url: string; note?: string | null; kind?: "link" | "arte" }) {
  return http<{ ok: true; reference: BrandReference }>(base("/references"), { method: "POST", body: JSON.stringify({ kind: "link", ...input }) });
}
export function deleteReference(id: string) { return http<{ ok: true }>(base(`/references/${encodeURIComponent(id)}`), { method: "DELETE" }); }
/** Sobe uma imagem de referência direto ao Storage da empresa e devolve o link público. */
export async function uploadReference(file: File): Promise<string> {
  const type = ["image/jpeg", "image/png", "image/webp"].includes(file.type) ? file.type : "";
  if (!type) throw new Error("Envie uma imagem JPG, PNG ou WEBP.");
  const target = await http<{ upload_url: string; public_url: string }>(base("/references/upload"), { method: "POST", body: JSON.stringify({ content_type: type }) });
  const response = await fetch(target.upload_url, { method: "PUT", body: file, headers: { "Content-Type": type, "x-upsert": "false" } });
  if (!response.ok) throw new Error(`O envio da imagem falhou (${response.status}).`);
  return target.public_url;
}
export function listItemReferences(itemId: string) { return http<{ references: BrandReference[] }>(base(`/calendar/items/${encodeURIComponent(itemId)}/references`)); }
export function addItemReference(itemId: string, input: { url: string; note?: string | null; kind?: "link" | "arte" }) {
  return http<{ ok: true; reference: BrandReference }>(base(`/calendar/items/${encodeURIComponent(itemId)}/references`), { method: "POST", body: JSON.stringify({ kind: "link", ...input }) });
}

// ---------------------------------------------------------------- conversa da marca e linha do tempo
export type ChatChannel = "cliente" | "equipe";
export type ChatMessage = { id: string; channel: ChatChannel; author_side: "cliente" | "mugo"; author_name: string | null; body: string;
  item_id: string | null; item_title: string | null; created_at: string; mine: boolean };
export type TimelineEvent = { id: string; at: string; side: "cliente" | "mugo"; kind: string; text: string; detail: string | null; item_id: string | null;
  actor?: string; title?: string | null; changes?: string[]; link?: string | null };
export function listChat(channel: ChatChannel) { return http<{ messages: ChatMessage[] }>(base(`/chat/${channel}`)); }
export function sendChat(channel: ChatChannel, body: string, itemId?: string | null) {
  return http<{ ok: true; message: ChatMessage }>(base(`/chat/${channel}`), { method: "POST", body: JSON.stringify({ body, ...(itemId ? { item_id: itemId } : {}) }) });
}
export function chatUnread() { return http<{ unread: Partial<Record<ChatChannel, number>> }>(base("/chat-unread")); }
export function listTimeline() { return http<{ events: TimelineEvent[] }>(base("/timeline")); }

// ---------------------------------------------------------------- conhecimento da marca (documentos alimentam a IA)
export type KnowledgeKind = "institucional" | "produto" | "campanha" | "tom_de_voz" | "restricao" | "outro" | "conversa";
/** pendente: guardado, IA ainda lendo · aprendido: entrou na memória · falhou: guardado, IA não leu (dá para tentar de novo). */
export type BrandDocumentStatus = "pendente" | "aprendido" | "falhou";
export type BrandDocument = { id: string; name: string; kind: KnowledgeKind; summary: string | null; facts_added: number; truncated: boolean; created_at: string;
  status?: BrandDocumentStatus; error?: string | null; chars_total?: number };
export type TeachResult = { ok: true; document: BrandDocument; knowledge: string; sources: number; warning?: string };
export type BrandKnowledge = { knowledge: string; sources: number; updated_at: string | null; documents: BrandDocument[] };
export function getKnowledge() { return http<BrandKnowledge>(base("/knowledge")); }
export function saveKnowledge(knowledge: string) { return http<{ ok: true; knowledge: string; sources: number }>(base("/knowledge"), { method: "PUT", body: JSON.stringify({ knowledge }) }); }
export const KNOWLEDGE_MAX_BYTES = 10 * 1024 * 1024;
async function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Não foi possível ler o arquivo."));
    reader.readAsDataURL(file);
  });
}
/** O arquivo vai ao servidor, vira conhecimento da IA e é descartado (não fica guardado). */
export function retryKnowledgeDocument(id: string) {
  return http<TeachResult>(base(`/knowledge/documents/${encodeURIComponent(id)}/retry`), { method: "POST", timeoutMs: 180_000 });
}
export function addKnowledgeFacts(facts: string[]) {
  return http<TeachResult>(base("/knowledge/facts"), { method: "POST", body: JSON.stringify({ facts }) });
}

export type BrandAgentSource = { name: string };
export type BrandAgentMessage = { id: string | null; role: "user" | "assistant"; content: string; created_at?: string;
  meta?: { on_topic?: boolean; sources?: BrandAgentSource[]; new_facts?: string[] } };
export type BrandAgentAnswer = { ok: true; id: string | null; answer: string; on_topic: boolean; sources: BrandAgentSource[]; new_facts: string[] };
export function getBrandAgent() { return http<{ messages: BrandAgentMessage[] }>(base("/brand-agent")); }
export function askBrandAgent(question: string) {
  return http<BrandAgentAnswer>(base("/brand-agent"), { method: "POST", body: JSON.stringify({ question }), timeoutMs: 60_000 });
}
export function clearBrandAgent() { return http<{ ok: true }>(base("/brand-agent"), { method: "DELETE" }); }

export async function teachFromFile(file: File, kind: KnowledgeKind) {
  if (file.size > KNOWLEDGE_MAX_BYTES) throw new Error("Arquivo grande demais (até 10 MB). Divida em partes.");
  return http<TeachResult>(base("/knowledge/documents"),
    { method: "POST", body: JSON.stringify({ file_name: file.name, kind, content_base64: await fileBase64(file) }), timeoutMs: 180_000 });
}
export function teachFromText(text: string, kind: KnowledgeKind, title = "Texto colado") {
  return http<TeachResult>(base("/knowledge/documents"),
    { method: "POST", body: JSON.stringify({ file_name: title, kind, text }), timeoutMs: 180_000 });
}

/** Link do Meta Business Suite já na Página desta marca. */
export function getPublisher() { return http<{ url: string; page_id: string | null; username: string | null }>(base("/publisher")); }

// ---------------------------------------------------------------- histórico de cada pauta (só equipe)
export type ItemEvent = { id: string; action: string; actor_name: string | null; actor_side: "mugo" | "cliente" | "sistema"; detail: string | null; created_at: string };
export type LatestEvent = { item_id: string; action: string; actor_name: string | null; actor_side: ItemEvent["actor_side"]; created_at: string };
export function getItemHistory(itemId: string) { return http<{ events: ItemEvent[] }>(base(`/calendar/items/${encodeURIComponent(itemId)}/history`)); }
export function getLatestHistory() { return http<{ latest: Record<string, LatestEvent> }>(base("/calendar/history/latest")); }
