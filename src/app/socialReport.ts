import { http, clientClientPath } from "./api";

/** Relatório social do mês (modelo "Social Media Report" da Mugô, 6 slides). */
const base = (path: string) => clientClientPath(`/studio/social-report${path}`);

export type ReportFormat = "reels" | "posts" | "stories";
export type ReportPost = {
  media_id: string; format: ReportFormat; timestamp: string | null; caption: string; permalink: string | null;
  views: number; reach: number; likes: number; comments: number; shares: number; saved: number;
  avg_watch_ms: number | null; follows?: number | null; typical_views?: number; times_typical?: number | null;
};
export type ReportData = {
  month: string; month_label: string; prev_month_label: string; brand: string; built_at: string;
  overview: {
    views: number | null; views_change_pct: number | null; non_follower_pct: number | null; non_follower_range: [number, number] | null;
    new_followers: number | null; contents: Record<ReportFormat, number>; contents_total: number; best_formats: ReportFormat[];
    profile_views: number | null; link_taps: number | null;
  };
  audience: {
    ages: { label: string; pct: number | null }[]; cities: { label: string; pct: number | null }[];
    gender: { homens: number; mulheres: number } | null; active: { day: string; hours: string }[];
  };
  highlight: ReportPost | null; prev_highlight: ReportPost | null;
  top: { likes: ReportPost[]; views: ReportPost[]; follows: ReportPost[]; engagement?: ReportPost[] };
};
export type SocialReport =
  | { month: string; built: false }
  | { month: string; built: true; data: ReportData; insights: string[]; images: Record<string, string>; updated_at: string | null };

const m = (month: string) => `/${encodeURIComponent(month)}`;
export const getSocialReport = (month: string) => http<SocialReport>(base(m(month)), { timeoutMs: 45_000 });
export const buildSocialReport = (month: string) => http<SocialReport>(base(`${m(month)}/build`), { method: "POST", timeoutMs: 150_000 });
export const draftReportInsights = (month: string) => http<{ insights: string[] }>(base(`${m(month)}/insights/draft`), { method: "POST", timeoutMs: 90_000 });
export const saveReportInsights = (month: string, insights: string[]) =>
  http<{ insights: string[] }>(base(`${m(month)}/insights`), { method: "PUT", body: JSON.stringify({ insights }) });

// ------------------------------------------------------------------ textos do modelo

const nf = (digits = 1) => new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits });

/** 10500 → "10,5 mil"; 1200000 → "1,2 mi"; 994 → "994". */
export function compact(value: number | null | undefined): string {
  if (value == null) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${nf().format(value / 1_000_000)} mi`;
  if (abs >= 1_000) return `${nf().format(value / 1_000)} mil`;
  return nf(0).format(value);
}

export const plus = (text: string) => (text === "—" ? text : `+${text}`);
export const pct = (value: number | null | undefined, digits = 1) => (value == null ? "—" : `${nf(digits).format(value)}%`);

const FORMAT_LABEL: Record<ReportFormat, [string, string]> = { reels: ["reel", "reels"], posts: ["post", "posts"], stories: ["story", "stories"] };
const NICE: Record<ReportFormat, string> = { reels: "Reels", posts: "posts", stories: "stories" };

export function viewsLine(o: ReportData["overview"], prevLabel: string): string {
  if (o.views_change_pct == null) return "visualizações";
  if (o.views_change_pct === 0) return `visualizações (igual a ${prevLabel})`;
  return `visualizações (${nf(0).format(Math.abs(o.views_change_pct))}% a ${o.views_change_pct < 0 ? "menos" : "mais"} que em ${prevLabel})`;
}

export function nonFollowerNote(o: ReportData["overview"]): string {
  if (!o.non_follower_range || o.non_follower_pct == null) return "";
  const values = [o.non_follower_pct, ...o.non_follower_range];
  const lo = Math.floor(Math.min(...values)), hi = Math.ceil(Math.max(...values));
  return lo === hi ? `(média dos últimos 3 meses: ${lo}%)` : `(média dos últimos 3 meses: ${lo}-${hi}%)`;
}

export function contentsNote(o: ReportData["overview"]): string {
  const parts = (["reels", "posts", "stories"] as ReportFormat[]).filter((f) => o.contents[f])
    .map((f) => `${o.contents[f]} ${FORMAT_LABEL[f][o.contents[f] === 1 ? 0 : 1]}`);
  if (!parts.length) return "";
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} e ${parts[parts.length - 1]}` : parts[0];
  const best = o.best_formats.map((f) => NICE[f]);
  const tail = best.length === 2 ? ` Os ${best[0]} e os ${best[1]} foram os formatos que melhor performaram.`
    : best.length === 1 ? ` Os ${best[0]} foram o formato que melhor performou.` : "";
  return `(${list}.${tail})`;
}

export function watch(ms: number | null | undefined): string {
  if (!ms) return "—";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

export function meaning(post: ReportPost): string {
  const kind = FORMAT_LABEL[post.format][0];
  if (post.times_typical && post.times_typical >= 1.2) {
    return `Teve ${nf().format(post.times_typical)}x as visualizações do seu ${kind} típico do mês: é o conteúdo que mais levou a marca para fora da base.`;
  }
  return `Foi o ${kind} com mais visualizações do mês, perto do desempenho típico da conta.`;
}

export const shortCaption = (text: string, max = 22) => {
  const clean = (text || "").replace(/\s+/g, " ").trim() || "Sem legenda";
  return clean.length > max ? `${clean.slice(0, max).trimEnd()}…` : clean;
};

export const postDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", timeZone: "America/Sao_Paulo" }) : "");

/** Fotos grandes (overview e audiência): os posts com mais interações que têm imagem, sem repetir. */
export function photoPosts(d: ReportData, images: Record<string, string>): [string | undefined, string | undefined] {
  const score = (p: ReportPost) => p.likes + p.comments + p.shares + p.saved;
  const pool = [...(d.top.engagement || []), ...d.top.likes, ...d.top.views, ...(d.highlight ? [d.highlight] : [])];
  const seen = new Set<string>();
  const ranked = pool.filter((p) => images[p.media_id] && !seen.has(p.media_id) && seen.add(p.media_id))
    .sort((a, b) => score(b) - score(a));
  return [ranked[0]?.media_id, ranked[1]?.media_id ?? ranked[0]?.media_id];
}

/** Mês fechado anterior em AAAA-MM (o relatório olha para trás). */
export function lastMonth(now = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export const capital = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);
