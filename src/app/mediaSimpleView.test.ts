import { describe, expect, it } from "vitest";
import type { CampaignAction, Diagnosis, Strategy } from "./media";
import { buildSimpleMediaView } from "./mediaSimpleView";

const totals = (patch: Partial<Diagnosis["recent"]> = {}): Diagnosis["recent"] => ({
  spend: 1000, impressions: 100000, clicks: 2000, conversions: 50, revenue: 5000,
  cpm: 10, cpc: 0.5, ctr: 0.02, cpa: 20, roas: 5, conversion_rate: 0.025, ...patch,
});

const strategy = (patch: Partial<Strategy> = {}): Strategy => ({
  month: "2026-12", objective: "vendas", metric: "revenue", metric_label: "receita atribuída", days: 30,
  window: { start: "2026-10-01", end: "2026-10-30", days: 30 },
  diagnosis: [{ channel: "meta", label: "Meta Ads", recent: totals(), previous: totals(), window: totals(),
    changes: { spend: 0, revenue: 0, roas: 0, cpa: 0, cpm: 0, ctr: 0, conversions: 0 }, confidence: "boa", days_with_spend: 30, monthly_spend: 1000, findings: [] }],
  store: {}, goal_revenue: null, margin: null, curves: {}, current_budget: 1000, scenarios: [], recommended: "eficiencia", selected: "eficiencia",
  weeks: [], guardrails: [], campaigns: [], waste: 0, findings: [], method: "fixture", boosts: { pool: 0, share: 0, posts: [], note: null },
  narrative: { headline: "Leitura", thesis: "Leitura existente", channel_roles: [], campaign_notes: [], creative_guidance: [], risks: [],
    next_7_days: ["Revisar a campanha A.", "Validar a campanha B.", "Acompanhar o custo.", "Esta quarta ação não entra."] },
  ...patch,
});

const campaign = (name: string, patch: Partial<CampaignAction> = {}): CampaignAction => ({
  channel: "meta", campaign: name, action: "manter", why: "eficiência acima da média observada", spend: 500,
  conversions: 10, revenue: 2000, roas: 4, cpa: 50, share: 0.5, planned_budget: 500, ...patch,
});

describe("Resumo Executivo de Mídia On", () => {
  it("resume apenas dados observados e prioriza até três campanhas de vendas independentemente da ordem", () => {
    const view = buildSimpleMediaView(strategy(), [
      campaign("Campanha B", { revenue: 3000 }), campaign("Campanha D", { revenue: 1000 }),
      campaign("Campanha A", { revenue: 5000, action: "escalar", learning: "A escala anterior manteve o ROAS." }), campaign("Campanha C", { revenue: 2000 }),
      campaign("Sugestão", { revenue: 9000, suggested: true }),
    ]);
    expect(view.summary).toContain("R$ 1.000");
    expect(view.wins.map((item) => item.campaign)).toEqual(["Campanha A", "Campanha B", "Campanha C"]);
    expect(view.wins[0].explanation).toBe("A escala anterior manteve o ROAS.");
    expect(view.wins.find((item) => item.campaign === "Campanha B")?.explanation).toBeNull();
    expect(view.recommendations).toHaveLength(3);
  });

  it("não usa conversões para inventar ranking de tráfego e explica a diferença entre clique e visita", () => {
    const view = buildSimpleMediaView(strategy({ objective: "trafego", metric: "clicks", metric_label: "cliques" }), [campaign("Campanha A")]);
    expect(view.wins).toEqual([]);
    expect(view.winsLimitation).toContain("cliques por campanha");
    expect(view.metrics.find((item) => item.label === "Cliques nos anúncios")?.explanation).toContain("não equivale necessariamente");
    expect(view.summary).toContain("2.000 cliques nos anúncios");
  });

  it("distingue impressões de alcance único e não atribui retenção a receita de mídia", () => {
    const reach = buildSimpleMediaView(strategy({ objective: "alcance", metric: "impressions", metric_label: "impressões" }), [campaign("Campanha A")]);
    expect(reach.metrics.find((item) => item.label === "Impressões")?.explanation).toContain("não equivale ao alcance");
    expect(reach.winsLimitation).toContain("alcance único");
    const retention = buildSimpleMediaView(strategy({ objective: "retencao" }), [campaign("Campanha A")]);
    expect(retention.wins).toEqual([]);
    expect(retention.winsLimitation).toContain("não comprovam retenção");
  });

  it("informa a ausência de dados sem substituir por projeções", () => {
    const empty = totals({ spend: 0, revenue: 0, conversions: 0, clicks: 0, impressions: 0 });
    const view = buildSimpleMediaView(strategy({ diagnosis: [{ ...strategy().diagnosis[0], recent: empty }] }), []);
    expect(view.summary).toContain("não há dados observados suficientes");
    expect(view.dataLimitation).toContain("não substitui dados ausentes por estimativas");
  });

  it("não transforma eficiência média do canal em explicação causal", () => {
    const view = buildSimpleMediaView(strategy(), [campaign("Campanha média", { why: "eficiência dentro da média do canal" })]);
    expect(view.wins[0].decisionReason).toBe("eficiência dentro da média do canal");
    expect(view.wins[0].explanation).toBeNull();
  });
});
