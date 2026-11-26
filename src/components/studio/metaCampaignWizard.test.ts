import { describe, expect, it } from "vitest";
import type { AdPayload, MetaStructure } from "../../app/metaAds";
import { metaStepIssues, META_STEPS } from "./metaCampaignWizard";

const meta = (patch: Partial<MetaStructure> = {}): MetaStructure => ({
  objective: "OUTCOME_SALES", special_ad_categories: [], budget_level: "campaign", budget_type: "daily", budget: 50,
  bid_strategy: "LOWEST_COST_WITHOUT_CAP", bid_amount: null, roas_floor: null, conversion_location: "WEBSITE", messaging_apps: [],
  performance_goal: "OFFSITE_CONVERSIONS", conversion_event: "PURCHASE", app: null, lead_form: null, phone_number: null,
  has_end_date: true, use_existing_post: false, ...patch,
});
const valid = (patch: Partial<MetaStructure> = {}): AdPayload => ({
  name: "Campanha de lançamento", objective: "vendas", meta: meta(patch),
  daily_budget: 50, start_date: "2026-11-19", end_date: "2026-11-30",
  audience: { age_min: 25, age_max: 55, gender: "todos",
    regions: ["São Paulo"], interests: ["Corrida"], advantage: false },
  ad: { primary_text: "Novo lançamento", headline: "Conheça", description: "",
    cta: "SHOP_NOW", link: "https://marca.com.br/produto",
    image_url: "https://marca.com.br/foto.png", calendar_item_id: null },
});

describe("Mídia ON — criador igual ao Gerenciador de Anúncios", () => {
  it("segue os 3 níveis da Meta e a revisão", () => {
    expect(META_STEPS).toEqual(["Campanha", "Conjunto de anúncios", "Anúncio", "Revisão"]);
  });
  it("campanha: orçamento e lance no nível da campanha", () => {
    expect(metaStepIssues(valid({ budget: 0 }), 0)).not.toHaveLength(0);
    expect(metaStepIssues(valid({ bid_strategy: "COST_CAP" }), 0)).toEqual(["Informe a meta de custo por resultado."]);
    expect(metaStepIssues(valid({ bid_strategy: "LOWEST_COST_WITH_MIN_ROAS", performance_goal: "VALUE" }), 0)).toEqual(["Informe a meta de ROAS."]);
    expect(metaStepIssues(valid({ budget_type: "lifetime", budget: 600 }), 0)).toEqual([]);
  });
  it("conjunto: datas, local de conversão e público", () => {
    expect(metaStepIssues({ ...valid(), end_date: "2026-11-18" }, 1)).not.toHaveLength(0);
    expect(metaStepIssues({ ...valid({ has_end_date: false }), end_date: "2026-11-18" }, 1)).toEqual([]);
    expect(metaStepIssues(valid({ budget_type: "lifetime", budget: 30 }), 1).join(" ")).toContain("Orçamento total baixo");
    expect(metaStepIssues(valid({ objective: "OUTCOME_LEADS", conversion_location: "ON_AD", performance_goal: "LEAD_GENERATION" }), 1))
      .toEqual(["Escolha o formulário instantâneo."]);
    expect(metaStepIssues({ ...valid(), audience: { ...valid().audience, age_min: 60, age_max: 30 } }, 1)).not.toHaveLength(0);
  });
  it("anúncio: arte e URL do site", () => {
    const input = valid();
    input.ad.image_url = "";
    input.ad.link = "";
    expect(metaStepIssues(input, 2)).toHaveLength(2);
    expect(metaStepIssues(input, 3)).toHaveLength(2);
  });
  it("aceita campanha completa e não pede site para reconhecimento nem para post existente", () => {
    expect(metaStepIssues(valid(), 3)).toEqual([]);
    const awareness = { ...valid({ objective: "OUTCOME_AWARENESS", conversion_location: "NONE", performance_goal: "REACH", conversion_event: null }),
      ad: { ...valid().ad, link: "" } };
    expect(metaStepIssues(awareness, 3)).toEqual([]);
    const post = { ...valid({ use_existing_post: true }), ad: { ...valid().ad, image_url: "", primary_text: "", instagram_post_id: "1790" } };
    expect(metaStepIssues(post, 2)).toEqual([]);
  });
  it("meta de vídeo exige vídeo", () => {
    const thru = valid({ objective: "OUTCOME_AWARENESS", conversion_location: "NONE", performance_goal: "THRUPLAY" });
    expect(metaStepIssues(thru, 2).join(" ")).toContain("vídeo");
  });
});
