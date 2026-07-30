import { format } from "date-fns";
import type { IgMediaItem, MonthAgg } from "./types";

function n(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function monthKey(ts?: string | null) {
  if (!ts) return "unknown";
  const raw = String(ts).trim();
  if (/^\d{4}-\d{2}/.test(raw)) return raw.slice(0, 7);
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "unknown";
  // Usa UTC para evitar deslocamento de timezone (ex.: março virar fevereiro).
  return format(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)), "yyyy-MM");
}

export function buildMonthAgg(media: IgMediaItem[]): MonthAgg[] {
  const map = new Map<string, MonthAgg>();

  for (const m of media) {
    const mk = monthKey(m.timestamp);
    if (mk === "unknown") continue;

    const cur = map.get(mk) || {
      month: mk,
      posts: 0,
      reels: 0,
      reach: 0,
      views: 0,
      interactions: 0,
      profile_visits: 0,
      likes: 0,
      comments: 0,
      shares: 0,
      saved: 0,
      avg_watch_ms: 0,
      skip_rate_avg: 0,
    };

    const type = (m.media_product_type || "").toUpperCase();
    if (type === "REELS") cur.reels += 1;
    else cur.posts += 1;

    const ins = m.insights || {};
    cur.reach += n(ins.reach);
    cur.views += n(ins.views);
    cur.interactions += n(ins.total_interactions);
    cur.profile_visits += n(ins.profile_visits);

    cur.likes += n(ins.likes);
    cur.comments += n(ins.comments);
    cur.shares += n(ins.shares);
    cur.saved += n(ins.saved);

    if (type === "REELS") {
      cur.avg_watch_ms += n(ins.ig_reels_avg_watch_time);
      cur.skip_rate_avg += n(ins.reels_skip_rate);
    }

    map.set(mk, cur);
  }

  for (const agg of map.values()) {
    if (agg.reels > 0) {
      agg.avg_watch_ms = Math.round(agg.avg_watch_ms / agg.reels);
      agg.skip_rate_avg = Math.round(agg.skip_rate_avg / agg.reels);
    } else {
      agg.avg_watch_ms = 0;
      agg.skip_rate_avg = 0;
    }
  }

  return Array.from(map.values()).sort((a, b) => (a.month > b.month ? 1 : -1));
}

export function monthsList(aggs: MonthAgg[]) {
  return aggs.map((a) => a.month);
}

export function getMonth(aggs: MonthAgg[], m: string) {
  return aggs.find((x) => x.month === m);
}

export function pct(now: number, prev: number) {
  if (!prev) return now ? 100 : 0;
  return Math.round(((now - prev) / prev) * 100);
}

