import { describe, expect, it } from "vitest";
import {
  buildTestIdeas,
  describeSources,
  rankInsights,
  selectMovements,
  selectOpportunities,
} from "./intelligencePriority";
import type { IntelligenceInsight, IntelligenceMetric } from "./intelligenceTypes";

function metric(id: string, overrides: Partial<IntelligenceMetric> = {}): IntelligenceMetric {
  return {
    id, label: `Métrica ${id}`, value: 100, format: "currency",
    status: "confirmed", source: "meta", previous_value: 90, variation_percent: 11,
    ...overrides,
  } as IntelligenceMetric;
}

function insight(overrides: Partial<IntelligenceInsight> = {}): IntelligenceInsight {
  return {
    category: "positive", title: "Título", interpretation: "Leitura.",
    metric_ids: ["revenue"], sources: ["meta"], impact: "medium", confidence: "medium",
    action: "Fazer algo.", reason: "Motivo.",
    ...overrides,
  } as IntelligenceInsight;
}

const metrics = new Map<string, IntelligenceMetric>([
  ["revenue", metric("revenue")],
  ["orders", metric("orders", { variation_percent: null })],
]);

describe("selectMovements — no máximo três, sempre com evidência", () => {
  it("nunca passa de três", () => {
    const many = Array.from({ length: 7 }, (_, index) => insight({ title: `T${index}` }));
    expect(selectMovements(many, metrics)).toHaveLength(3);
  });

  it("menos de três é resposta válida, sem preencher por obrigação", () => {
    expect(selectMovements([insight()], metrics)).toHaveLength(1);
    expect(selectMovements([], metrics)).toEqual([]);
    expect(selectMovements(null, metrics)).toEqual([]);
  });

  it("insight sem evidência não vira movimento", () => {
    const grounded = insight({ title: "Com evidência" });
    const ungrounded = insight({ title: "Sem evidência", metric_ids: [], impact: "high", confidence: "high" });
    const selected = selectMovements([ungrounded, grounded], metrics);
    expect(selected.map((item) => item.title)).toEqual(["Com evidência"]);
  });

  it("metric_ids vazio ou em branco não conta como evidência", () => {
    expect(selectMovements([insight({ metric_ids: ["  "] })], metrics)).toEqual([]);
  });

  it("risco vem antes de leitura positiva de mesmo impacto", () => {
    const positive = insight({ title: "Positivo", category: "positive" });
    const risk = insight({ title: "Risco", category: "risk" });
    expect(selectMovements([positive, risk], metrics)[0].title).toBe("Risco");
  });

  it("impacto e confiança ordenam dentro da mesma categoria", () => {
    const low = insight({ title: "Baixo", impact: "low", confidence: "low" });
    const high = insight({ title: "Alto", impact: "high", confidence: "high" });
    const medium = insight({ title: "Médio", impact: "medium", confidence: "medium" });
    expect(selectMovements([low, medium, high], metrics).map((item) => item.title))
      .toEqual(["Alto", "Médio", "Baixo"]);
  });

  it("métrica com variação no período pesa como sinal recente", () => {
    const recent = insight({ title: "Recente", metric_ids: ["revenue"] });
    const stale = insight({ title: "Sem variação", metric_ids: ["orders"] });
    expect(selectMovements([stale, recent], metrics)[0].title).toBe("Recente");
  });

  it("qualidade de dado não disputa o destaque com negócio", () => {
    const quality = insight({ title: "Qualidade", category: "data_quality", impact: "high", confidence: "high" });
    const business = insight({ title: "Negócio", category: "opportunity", impact: "low", confidence: "low" });
    expect(rankInsights([quality, business], metrics)[0].title).toBe("Negócio");
  });

  it("ordenação é estável e não altera a lista recebida", () => {
    const list = [insight({ title: "A" }), insight({ title: "B" })];
    const copy = [...list];
    rankInsights(list, metrics);
    expect(list).toEqual(copy);
  });
});

describe("selectOpportunities — aterradas e sem repetir o destaque", () => {
  it("só categoria oportunidade com evidência", () => {
    const list = [
      insight({ title: "Oportunidade", category: "opportunity" }),
      insight({ title: "Risco", category: "risk" }),
      insight({ title: "Sem dado", category: "opportunity", metric_ids: [] }),
    ];
    expect(selectOpportunities(list, metrics).map((item) => item.title)).toEqual(["Oportunidade"]);
  });

  it("não repete o que já está nos movimentos", () => {
    const opportunity = insight({ title: "Mesma", category: "opportunity" });
    expect(selectOpportunities([opportunity], metrics, [opportunity])).toEqual([]);
  });

  it("sem candidata aterrada, devolve vazio em vez de encher a seção", () => {
    expect(selectOpportunities([insight({ category: "risk" })], metrics)).toEqual([]);
  });
});

describe("buildTestIdeas — derivadas da análise, nunca inventadas", () => {
  const action = {
    priority: "week" as const, recommendation: "Testar novo público",
    justification: "Sobreposição baixa de audiência.", sources: ["meta"],
    impact_expected: "Mais conversões ao mesmo custo", confidence: "medium" as const,
    metric_id: "revenue",
  };
  const analysis = {
    executive: { overall: "", main_change: "", opportunity: "", attention: "", priority_action: "" },
    insights: [],
    actions: [action],
  };

  it("mapeia os campos da recomendação, sem texto novo", () => {
    const [idea] = buildTestIdeas(analysis, metrics);
    expect(idea.title).toBe("Testar novo público");
    expect(idea.whyNow).toBe("Sobreposição baixa de audiência.");
    expect(idea.action).toBe("Testar nesta semana");
    expect(idea.hypothesis).toBe("Mais conversões ao mesmo custo");
    expect(idea.metricLabel).toBe("Métrica revenue");
  });

  it("recomendação sem métrica existente é descartada", () => {
    const orphan = { ...action, metric_id: "inexistente" };
    expect(buildTestIdeas({ ...analysis, actions: [orphan] }, metrics)).toEqual([]);
  });

  it("limita a quatro e não repete título", () => {
    const many = Array.from({ length: 9 }, (_, index) => ({ ...action, recommendation: `Ideia ${index}` }));
    expect(buildTestIdeas({ ...analysis, actions: many }, metrics)).toHaveLength(4);
    const duplicated = [action, { ...action }];
    expect(buildTestIdeas({ ...analysis, actions: duplicated }, metrics)).toHaveLength(1);
  });

  it("sem análise não há ideias", () => {
    expect(buildTestIdeas(null, metrics)).toEqual([]);
    expect(buildTestIdeas({ ...analysis, actions: [] }, metrics)).toEqual([]);
  });
});

describe("describeSources — nome humano, sem detalhe interno", () => {
  it("usa o provider real do comércio no lugar do rótulo genérico", () => {
    const names = describeSources({
      sources: [
        { id: "commerce", label: "E-commerce", status: "available" },
        { id: "meta", label: "Meta Ads", status: "available" },
      ],
      commerce_context: { provider_label: "FBITS/Wake", official_kpis: true },
    });
    expect(names).toEqual(["FBITS/Wake", "Meta Ads"]);
  });

  it("Shopify aparece com o próprio nome", () => {
    const names = describeSources({
      sources: [{ id: "commerce", label: "E-commerce", status: "available" }],
      commerce_context: { provider_label: "Shopify", official_kpis: false },
    });
    expect(names).toEqual(["Shopify"]);
  });

  it("fonte sem dado no período não entra na nota", () => {
    const names = describeSources({
      sources: [
        { id: "meta", label: "Meta Ads", status: "available" },
        { id: "ga4", label: "Google Analytics 4", status: "connected_no_data" },
        { id: "google_ads", label: "Google Ads", status: "partial" },
      ],
    });
    expect(names).toEqual(["Meta Ads", "Google Ads"]);
  });

  it("sem snapshot, nenhuma fonte é afirmada", () => {
    expect(describeSources(null)).toEqual([]);
    expect(describeSources({})).toEqual([]);
  });
});
