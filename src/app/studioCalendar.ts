import { localParts, type CalendarItem, type StudioFormat } from "./studio";

export type ViewMode = "mes" | "semana" | "dia";
export type PostDraft = { date: string; time: string; format: StudioFormat; pillar: string; title: string; hook: string; caption_draft: string; rationale: string };

/** Datas como "AAAA-MM-DD" sem fuso: o calendário inteiro raciocina no dia de São Paulo. */
export const toKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const fromKey = (key: string) => { const [y, m, d] = key.split("-").map(Number); return new Date(y, m - 1, d); };
export const addDays = (key: string, n: number) => { const d = fromKey(key); d.setDate(d.getDate() + n); return toKey(d); };
export const mondayOf = (key: string) => { const d = fromKey(key); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return toKey(d); };
export const todayKey = () => toKey(new Date());

export function draftFrom(item: CalendarItem): PostDraft {
  const { date, time } = localParts(item.scheduled_at);
  return { date, time, format: item.format, pillar: item.pillar || "", title: item.title, hook: item.hook || "",
    caption_draft: item.caption_draft || "", rationale: item.rationale || "" };
}
