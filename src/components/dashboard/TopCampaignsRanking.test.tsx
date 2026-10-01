import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import TopCampaignsRanking from "./TopCampaignsRanking";
import type { CampaignRankingRow } from "../../app/types";

function row(overrides: Partial<CampaignRankingRow>): CampaignRankingRow {
  return {
    campaign_id: "1",
    campaign_name: "Campanha",
    spend: 100,
    impressions: 1000,
    reach: 800,
    clicks: 50,
    conversions: 2,
    revenue: 300,
    cpc: 2,
    cpm: 10,
    ctr: 5,
    roas: 3,
    ...overrides,
  };
}

describe("TopCampaignsRanking — ranking editorial, não tabela pesada", () => {
  it("mostra estado vazio quando não há campanhas", () => {
    const markup = renderToStaticMarkup(<TopCampaignsRanking campaigns={[]} />);
    expect(markup).toContain("Sem campanhas com investimento neste período.");
  });

  it("ordena por investimento e mostra o ranking em barras horizontais", () => {
    const campaigns = [
      row({ campaign_id: "a", campaign_name: "Campanha A", spend: 8200, roas: 5, conversions: 10 }),
      row({ campaign_id: "b", campaign_name: "Campanha B", spend: 4100, roas: 2, conversions: 3 }),
      row({ campaign_id: "c", campaign_name: "Campanha C", spend: 2900, roas: null, conversions: 0 }),
    ];
    const markup = renderToStaticMarkup(<TopCampaignsRanking campaigns={campaigns} />);
    const posA = markup.indexOf("Campanha A");
    const posB = markup.indexOf("Campanha B");
    const posC = markup.indexOf("Campanha C");
    expect(posA).toBeGreaterThan(-1);
    expect(posA).toBeLessThan(posB);
    expect(posB).toBeLessThan(posC);
    expect(markup).toContain("topCampaignsBarFill");
  });

  it("nunca mostra apenas o ID quando o nome da campanha é numérico", () => {
    const campaigns = [row({ campaign_id: "123456", campaign_name: "123456" })];
    const markup = renderToStaticMarkup(<TopCampaignsRanking campaigns={campaigns} />);
    expect(markup).toContain("Campanha — 123456");
  });

  it("destaca melhor ROAS, maior investimento, maior custo por compra e campanha sem compra", () => {
    const campaigns = [
      row({ campaign_id: "a", campaign_name: "A", spend: 1000, roas: 6, conversions: 5 }),
      row({ campaign_id: "b", campaign_name: "B", spend: 3000, roas: 1, conversions: 1 }),
      row({ campaign_id: "c", campaign_name: "C", spend: 500, roas: null, conversions: 0 }),
    ];
    const markup = renderToStaticMarkup(<TopCampaignsRanking campaigns={campaigns} />);
    expect(markup).toContain("Melhor ROAS");
    expect(markup).toContain("Maior investimento");
    expect(markup).toContain("Maior custo por compra");
    expect(markup).toContain("Sem compra");
  });

  it("não declara uma campanha de uma compra como melhor ROAS", () => {
    const markup = renderToStaticMarkup(<TopCampaignsRanking campaigns={[
      row({ campaign_id: "small", campaign_name: "Amostra", spend: 100, roas: 12, conversions: 1 }),
      row({ campaign_id: "scale", campaign_name: "Escala", spend: 3000, roas: 4, conversions: 20 }),
    ]} />);
    expect(markup).toContain("Amostra pequena");
    expect(markup).toMatch(/Melhor ROAS[\s\S]*Escala/);
  });
});
