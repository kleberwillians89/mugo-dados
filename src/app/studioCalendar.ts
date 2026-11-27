import { cleanDirection, localParts, type CalendarItem, type CreativeDirection, type StudioBriefing, type ProductTag, type ReelsOptions, type StudioChannel, type StudioFormat } from "./studio";

export type ViewMode = "mes" | "semana" | "dia" | "fluxo";
export type PostDraft = { date: string; time: string; channel?: StudioChannel; format: StudioFormat; pillar: string; title: string; hook: string; caption_draft: string; rationale: string; art_url?: string; collaborators?: string[]; product_tags?: ProductTag[]; reels_options?: ReelsOptions; creative_direction?: CreativeDirection;
  /** Briefing da peça em edição ("Editar peça"). */
  piece?: PieceDraft; destinations?: import("./studio").PublicationDestination[]; publication_group_id?: string };

/** Briefing da peça como a tela edita: textos simples e listas (uma linha por item). */
export type PieceDraft = { briefing: StudioBriefing; script: string; visual_idea: string };
export function pieceFrom(item: Pick<CalendarItem, "signals" | "script" | "visual_idea">): PieceDraft {
  return { briefing: { ...(item.signals?.briefing || {}) }, script: item.script || "", visual_idea: item.visual_idea || "" };
}
/** O que vai no PATCH quando o briefing da peça mudou: todos os campos (vazio apaga), listas sem linhas vazias. */
export function piecePatch(piece: PieceDraft) {
  const b = piece.briefing;
  const text = (v?: string) => (v || "").trim();
  const list = (v?: string[]) => (v || []).map((x) => x.trim()).filter(Boolean);
  return { script: text(piece.script), visual_idea: text(piece.visual_idea),
    briefing: { angle: text(b.angle), summary: text(b.summary), objective: text(b.objective), key_message: text(b.key_message), tone: text(b.tone),
      target_audience: text(b.target_audience), deliverables: list(b.deliverables), tech_requirements: list(b.tech_requirements) } };
}

/** Datas como "AAAA-MM-DD" sem fuso: o calendário inteiro raciocina no dia de São Paulo. */
export const toKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const fromKey = (key: string) => { const [y, m, d] = key.split("-").map(Number); return new Date(y, m - 1, d); };
export const addDays = (key: string, n: number) => { const d = fromKey(key); d.setDate(d.getDate() + n); return toKey(d); };
export const mondayOf = (key: string) => { const d = fromKey(key); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return toKey(d); };
export const todayKey = () => toKey(new Date());

export function draftFrom(item: CalendarItem): PostDraft {
  const { date, time } = localParts(item.scheduled_at);
  return { date, time, channel: item.channel || "instagram", format: item.format, pillar: item.pillar || "", title: item.title, hook: item.hook || "",
    caption_draft: item.caption_draft || "", rationale: item.rationale || "", art_url: item.art_url || "",
    collaborators: item.collaborators || [], product_tags: item.product_tags || [], reels_options: item.reels_options || {},
    creative_direction: cleanDirection(item.creative_direction), piece: pieceFrom(item) };
}
