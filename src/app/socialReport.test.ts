import { describe, expect, it } from "vitest";
import { compact, contentsNote, lastMonth, nonFollowerNote, viewsLine, watch, type ReportData } from "./socialReport";
import { getAppRouteFromPath, getPathForRoute } from "./routes";

const ov = (patch: Partial<ReportData["overview"]> = {}): ReportData["overview"] => ({
  views: 10500, views_change_pct: -29, non_follower_pct: 42.2, non_follower_range: [40.1, 49.6], new_followers: 12,
  contents: { reels: 7, posts: 4, stories: 27 }, contents_total: 38, best_formats: ["stories", "reels"], profile_views: 203, link_taps: 6, ...patch,
});

describe("relatório social: textos do modelo", () => {
  it("formata números como no modelo", () => {
    expect(compact(10500)).toBe("10,5 mil");
    expect(compact(994)).toBe("994");
    expect(compact(1_200_000)).toBe("1,2 mi");
    expect(compact(null)).toBe("—");
    expect(watch(9400)).toBe("9 s");
    expect(watch(null)).toBe("—");
  });

  it("monta as frases do overview a partir dos números", () => {
    expect(viewsLine(ov(), "agosto")).toBe("visualizações (29% a menos que em agosto)");
    expect(viewsLine(ov({ views_change_pct: 12.4 }), "agosto")).toBe("visualizações (12% a mais que em agosto)");
    expect(viewsLine(ov({ views_change_pct: null }), "agosto")).toBe("visualizações");
    expect(nonFollowerNote(ov())).toBe("(média dos últimos 3 meses: 40-50%)");
    expect(nonFollowerNote(ov({ non_follower_range: null }))).toBe("");
    expect(contentsNote(ov())).toBe("(7 reels, 4 posts e 27 stories. Os stories e os Reels foram os formatos que melhor performaram.)");
    expect(contentsNote(ov({ contents: { reels: 1, posts: 0, stories: 0 }, best_formats: [] }))).toBe("(1 reel.)");
  });

  it("abre no mês fechado anterior e tem rota própria", () => {
    expect(lastMonth(new Date(2026, 0, 15))).toBe("2025-12");
    expect(lastMonth(new Date(2026, 10, 3))).toBe("2026-10");
    expect(getAppRouteFromPath("/relatorio-social")).toBe("social_report");
    expect(getPathForRoute("social_report")).toBe("/relatorio-social");
  });
});
