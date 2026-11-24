import { describe, expect, it } from "vitest";
import type { DashboardDailyMetric } from "./DashboardDataContext";
import { last30Days, mediaKpis } from "./mediaKpis";

const day = (o: Partial<DashboardDailyMetric>) => o as DashboardDailyMetric;

describe("indicadores compactos da Mídia On", () => {
  it("Meta: soma o somável e calcula as razões no total, sem alcance somado", () => {
    const out = mediaKpis("meta", [
      day({ meta_spend: 100, meta_purchases: 2, meta_attributed_revenue: 500, meta_link_clicks: 400, meta_impressions: 20000, meta_reach: 15000 }),
      day({ meta_spend: 100, meta_purchases: 2, meta_attributed_revenue: 300, meta_link_clicks: 600, meta_impressions: 30000, meta_reach: 15000 }),
      day({ google_ads_spend: 999 }),
    ]);
    const v = Object.fromEntries(out.kpis.map((k) => [k.key, k.value]));
    expect(out.daysWithData).toBe(2);
    expect(v.spend).toMatch(/R\$\s*200,00/);
    expect(v.results).toBe("4");
    expect(v.cost).toMatch(/R\$\s*50,00/);
    expect(v.roas).toBe("4,00");
    expect(v.cpc).toMatch(/R\$\s*0,20/);
    expect(v.ctr).toBe("2,00%");
    expect(out.kpis.some((k) => /alcan/i.test(k.label))).toBe(false);
  });

  it("não inventa custo por resultado nem ROAS sem base (ex.: tráfego e alcance)", () => {
    const out = mediaKpis("meta", [day({ meta_spend: 181.81, meta_purchases: 0, meta_attributed_revenue: 0, meta_link_clicks: 1936, meta_impressions: 64000 })]);
    expect(out.kpis.map((k) => k.key)).toEqual(["spend", "clicks", "cpc", "ctr"]);
  });

  it("Google separado da Meta; sem dados = indisponível", () => {
    const rows = [day({ meta_spend: 50 }), day({ google_ads_spend: 80, google_ads_conversions: 4, google_ads_conversion_value: 320, google_ads_clicks: 100, google_ads_impressions: 4000 })];
    const g = mediaKpis("google", rows);
    expect(Object.fromEntries(g.kpis.map((k) => [k.key, k.value])).spend).toMatch(/R\$\s*80,00/);
    expect(mediaKpis("google", [day({ meta_spend: 50 })]).available).toBe(false);
  });

  it("período: 30 dias fechados até ontem", () => {
    expect(last30Days(new Date(2026, 10, 24, 15))).toEqual({ start: "2026-10-25", end: "2026-11-23" });
  });
});
