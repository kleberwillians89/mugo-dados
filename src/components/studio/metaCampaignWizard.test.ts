import { describe, expect, it } from "vitest";
import type { AdPayload } from "../../app/metaAds";
import { metaStepIssues, META_STEPS } from "./metaCampaignWizard";

const valid = (): AdPayload => ({
  name: "Campanha de lançamento", objective: "vendas",
  daily_budget: 50, start_date: "2026-11-19", end_date: "2026-11-30",
  audience: { age_min: 25, age_max: 55, gender: "todos",
    regions: ["São Paulo"], interests: ["Corrida"], advantage: false },
  ad: { primary_text: "Novo lançamento", headline: "Conheça", description: "",
    cta: "SHOP_NOW", link: "https://marca.com.br/produto",
    image_url: "https://marca.com.br/foto.png", calendar_item_id: null },
});

describe("Mídia ON — preparação guiada de Meta Ads", () => {
  it("has four explicit steps: campaign, audience, creative, review", () => {
    expect(META_STEPS).toEqual(["Campanha", "Público", "Criativo", "Revisão"]);
  });
  it("rejects an invalid budget or date before choosing audience", () => {
    expect(metaStepIssues({ ...valid(), daily_budget: 0 }, 0)).not.toHaveLength(0);
    expect(metaStepIssues({ ...valid(), end_date: "2026-11-18" }, 0)).not.toHaveLength(0);
  });
  it("requires valid age range before creative selection", () => {
    expect(metaStepIssues({ ...valid(), audience: { ...valid().audience, age_min: 60, age_max: 30 } }, 1)).not.toHaveLength(0);
  });
  it("rejects missing artwork and destination before review", () => {
    const input = valid();
    input.ad.image_url = "";
    input.ad.link = "";
    expect(metaStepIssues(input, 2)).toHaveLength(2);
    expect(metaStepIssues(input, 3)).toHaveLength(2);
  });
  it("accepts a complete campaign and does not require site link for awareness", () => {
    expect(metaStepIssues(valid(), 3)).toEqual([]);
    const awareness = { ...valid(), objective: "alcance" as const,
      ad: { ...valid().ad, link: "" } };
    expect(metaStepIssues(awareness, 3)).toEqual([]);
  });
});
