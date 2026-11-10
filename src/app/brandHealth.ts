import { http, clientClientPath } from "./api";

/** Saúde da marca (Clipping): volume e sentimento das menções e alertas de termos sensíveis. */
export type Grain = "day" | "week" | "month" | "quarter" | "year";
export type Source = "news" | "comments" | "direct";
export type HealthSentiment = "positivo" | "neutro" | "misto" | "negativo";
export type Split = Record<HealthSentiment | "sem_analise", number>;
export type HealthAlert = {
  id: string; kind: "termo" | "queda_indice" | "negativas"; term: string | null; severity: "medio" | "alto"; mentions: number;
  sources: Source[]; sample: string | null; detail: string | null; status: "aberto" | "resolvido";
  first_seen_at: string; last_seen_at: string; resolved_at: string | null;
};
export type BrandHealth = {
  period: { start: string; end: string; grain: Grain; previous_start: string; previous_end: string };
  sources: Source[];
  kpis: {
    index: number | null; index_previous: number | null; index_label: string | null;
    mentions: number; mentions_previous: number; mentions_change: number | null;
    net: number | null; net_previous: number | null; negative: number; negative_share: number | null; negative_share_previous: number | null;
    unanalyzed: number; alerts_open: number | null; alerts_high: number | null;
  };
  split: Split;
  series: (Split & { bucket: string; total: number; net: number | null })[];
  channels: { source: Source; mentions: number; previous: number; change: number | null; split: Split }[];
  themes: { theme: string; mentions: number; previous: number; change: number | null; tone: HealthSentiment | null }[];
  alerts: HealthAlert[];
};
export type HealthSettings = { sensitive_terms: string[]; index_drop_points: number; negative_day_pct: number; saved: boolean };

const base = (path: string) => clientClientPath(`/studio/clipping/health${path}`);
export const getBrandHealth = (q: { start: string; end: string; grain: Grain; sources: Source[] }) =>
  http<BrandHealth>(base(`?start=${q.start}&end=${q.end}&grain=${q.grain}&sources=${q.sources.join(",")}`), { timeoutMs: 45_000 });
export const getHealthAlerts = () => http<{ alerts: HealthAlert[]; settings: HealthSettings }>(base("/alerts"));
export const resolveHealthAlert = (id: string) => http<HealthAlert>(base(`/alerts/${encodeURIComponent(id)}/resolve`), { method: "POST" });
export const saveHealthSettings = (input: Partial<Omit<HealthSettings, "saved">>) =>
  http<HealthSettings>(base("/settings"), { method: "PUT", body: JSON.stringify(input) });

export const SENTIMENT_ORDER: HealthSentiment[] = ["positivo", "neutro", "misto", "negativo"];
export const SENTIMENT_NAME: Record<HealthSentiment, string> = { positivo: "Positivo", neutro: "Neutro", misto: "Misto", negativo: "Negativo" };
export const SOURCE_NAME: Record<Source, string> = { news: "Notícias e blogs", comments: "Comentários Instagram", direct: "Direct Instagram" };
export const SOURCE_CHIP: Record<Source, string> = { news: "Notícias", comments: "Comentários IG", direct: "Direct IG" };
export const GRAIN_NAME: Record<Grain, string> = { day: "Dia", week: "Semana", month: "Mês", quarter: "Trimestre", year: "Ano" };

/** Datas em São Paulo, formato AAAA-MM-DD. */
export const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const parseIso = (value: string) => { const [y, m, d] = value.split("-").map(Number); return new Date(y, m - 1, d); };
export const PRESETS = ["today", "7d", "30d", "month", "3m", "quarter", "year"] as const;
export type Preset = (typeof PRESETS)[number] | "custom";
export const PRESET_NAME: Record<Preset, string> = {
  today: "Hoje", "7d": "Últimos 7 dias", "30d": "Últimos 30 dias", month: "Este mês", "3m": "Últimos 3 meses",
  quarter: "Este trimestre", year: "Este ano", custom: "Personalizado",
};
export function presetRange(preset: Exclude<Preset, "custom">, today = new Date()): { start: string; end: string } {
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const back = (days: number) => new Date(end.getFullYear(), end.getMonth(), end.getDate() - days);
  const start = {
    today: end, "7d": back(6), "30d": back(29), month: new Date(end.getFullYear(), end.getMonth(), 1),
    "3m": new Date(end.getFullYear(), end.getMonth() - 3, end.getDate() + 1),
    quarter: new Date(end.getFullYear(), Math.floor(end.getMonth() / 3) * 3, 1), year: new Date(end.getFullYear(), 0, 1),
  }[preset];
  return { start: iso(start), end: iso(end) };
}
/** Rótulo do período agrupado (bucket = início do dia/semana/mês/trimestre/ano). */
export function bucketLabel(bucket: string, grain: Grain, long = false): string {
  const d = parseIso(bucket);
  if (grain === "year") return String(d.getFullYear());
  if (grain === "quarter") return `${Math.floor(d.getMonth() / 3) + 1}º tri ${d.getFullYear()}`;
  if (grain === "month") return d.toLocaleDateString("pt-BR", { month: long ? "long" : "short", year: "2-digit" }).replace(".", "");
  const short = d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return grain === "week" && long ? `Semana de ${short}` : short;
}
export type AnalyzeResult = { classified: number; failed: number; news_analyzed: number; news_pending: number; alerts_opened: number };
export const analyzeBrandHealth = () => http<AnalyzeResult>(base("/analyze"), { method: "POST", timeoutMs: 180_000 });
