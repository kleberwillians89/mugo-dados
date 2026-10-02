// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  period: { start: "2026-08-01", end: "2026-08-31" },
}));

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => "amalie",
  getActiveClientName: () => "Amalie",
}));

vi.mock("../app/PeriodContext", () => ({
  usePeriod: () => ({ period: mocks.period, setPeriod: () => {} }),
}));

const analysis = {
  id: "an-1",
  client_id: "amalie",
  period_start: "2026-08-01",
  period_end: "2026-08-31",
  status: "completed" as const,
  provider: "openai",
  model: "gpt",
  sources: [],
  data_quality: { score: 90, status: "good" as const, available_sources: 2, total_sources: 2, errors: 0, message: "ok" },
  metrics_snapshot: [
    { id: "spend", label: "Investimento", value: 1000, format: "currency" as const, status: "confirmed" as const, source: "meta_ads", previous_value: 900, variation_percent: 11 },
  ],
  analysis: {
    executive: {
      overall: "Receita cresceu no período.",
      main_change: "Receita +11%",
      opportunity: "Ampliar orçamento em Meta Ads.",
      attention: "CPA subiu 5%.",
      priority_action: "Revisar campanhas com CPA alto.",
    },
    insights: [
      { category: "positive" as const, title: "Receita em alta", interpretation: "A receita cresceu de forma consistente.", metric_ids: ["spend"], sources: ["meta_ads"], impact: "high" as const, confidence: "high" as const, action: "Manter o investimento atual.", reason: "Tendência estável nas últimas semanas." },
      { category: "risk" as const, title: "CPA subindo", interpretation: "O custo por aquisição aumentou.", metric_ids: ["spend"], sources: ["meta_ads"], impact: "medium" as const, confidence: "medium" as const, action: "Revisar segmentação.", reason: "Aumento de 5% no período." },
      { category: "opportunity" as const, title: "Público não explorado", interpretation: "Existe público com bom potencial de conversão.", metric_ids: ["spend"], sources: ["meta_ads"], impact: "medium" as const, confidence: "low" as const, action: "Testar novo público.", reason: "Baixa sobreposição de audiência." },
    ],
    actions: [
      { priority: "now" as const, recommendation: "Revisar campanha X", justification: "CPA acima da média.", sources: ["meta_ads"], impact_expected: "Redução de CPA", confidence: "medium" as const, metric_id: "spend" },
    ],
  },
  error_code: null,
  created_at: "2026-08-31T12:00:00Z",
  completed_at: "2026-08-31T12:00:00Z",
};

const snapshot = {
  client: { id: "amalie", name: "Amalie" },
  period: { start: "2026-08-01", end: "2026-08-31", days: 31, previous_start: "2026-07-01", previous_end: "2026-07-31" },
  sources: [
    { id: "meta_ads", label: "Meta Ads", status: "available" as const, connected: true, data_points: 30, covered_days: 30, last_sync_at: "2026-08-31T12:00:00Z" },
    { id: "google_ads", label: "Google Ads", status: "connected_no_data" as const, connected: true, data_points: 0, covered_days: 0, last_sync_at: null },
  ],
  quality: { score: 90, status: "good" as const, available_sources: 2, total_sources: 2, errors: 0, message: "ok" },
  last_sync_at: "2026-08-31T12:00:00Z",
  metrics: analysis.metrics_snapshot,
  crossings: [],
  top_campaigns: [],
};

const state = {
  snapshot: snapshot as Record<string, unknown>,
  analysis: analysis as Record<string, unknown>,
};

vi.mock("../app/api", () => ({
  getIntelligenceContext: vi.fn(async () => ({ ok: true, snapshot: state.snapshot })),
  getLatestIntelligenceAnalysis: vi.fn(async () => ({ ok: true, provider_configured: true, analysis: state.analysis })),
  getIntelligenceHistory: vi.fn(async () => ({ ok: true, items: [state.analysis] })),
  generateIntelligenceAnalysis: vi.fn(async () => ({ ok: true, provider_configured: true, status: "completed", snapshot: state.snapshot, analysis: state.analysis })),
  askIntelligence: vi.fn(),
}));

import Intelligence from "./Intelligence";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  state.snapshot = snapshot;
  state.analysis = analysis;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function renderIntelligence(canRefresh = true) {
  await act(async () => {
    root.render(<Intelligence onLogout={() => {}} canRefresh={canRefresh} />);
  });
  await act(async () => Promise.resolve());
  await act(async () => Promise.resolve());
}

describe("Intelligence — apresentação escaneável (não parece um chat)", () => {
  it("agrupa insights em Avanços, Riscos e Oportunidades", async () => {
    await renderIntelligence();
    const groupTitles = [...container.querySelectorAll(".intelInsightGroupTitle")].map((el) => el.textContent);
    expect(groupTitles).toEqual(["Avanços", "Riscos", "Oportunidades"]);
  });

  it("mostra os badges Fato, Interpretação e Recomendação em cada insight", async () => {
    await renderIntelligence();
    const badges = [...container.querySelectorAll(".intelInsightBadge")].map((el) => el.textContent);
    expect(badges).toContain("Fato");
    expect(badges).toContain("Interpretação");
    expect(badges).toContain("Recomendação");
  });

  it("mostra o resumo executivo no topo, antes dos insights", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("Resumo executivo");
    expect(container.textContent).toContain("Receita cresceu no período.");
  });

  it("mostra a fonte de cada métrica de evidência", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("meta_ads");
  });

  it("traduz status técnico de fonte para linguagem do cliente", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("Conectado • sem dados no período");
    expect(container.textContent).not.toContain("connected_no_data");
  });

  it("mantém a análise gerada sem banner de erro atrasado", async () => {
    await renderIntelligence();
    const button = [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizar análise");
    await act(async () => button?.click());
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain("Receita cresceu no período.");
    expect(container.querySelector(".intelError")).toBeNull();
  });

  it("não mostra a ação de atualizar análise para viewer", async () => {
    await renderIntelligence(false);
    expect(container.textContent).not.toContain("Atualizar análise");
  });
});

describe("Intelligence — provider de e-commerce e pesquisa externa", () => {
  const researchItem = {
    kind: "POTENTIAL_UGC_CREATOR" as const,
    handle: "@perfil", platform: "Instagram", profile_url: "https://exemplo/perfil",
    category: "Vinhos", reason_relevant: "Publica review de rótulos nacionais",
    observed_format: "Reels", public_signal: "Comentários pedindo indicação",
    source_url: "https://exemplo/post", researched_at: "2026-10-02T12:00:00Z",
  };

  it("mostra a plataforma de vendas resolvida, com indicadores oficiais no FBITS", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true,
        status: "ok", kpi_source: "fbits_dashboard", official_kpis: true,
      },
    };
    await renderIntelligence();
    const badge = container.querySelector('[data-testid="intel-commerce-provider"]');
    expect(badge?.textContent).toContain("FBITS/Wake");
    expect(badge?.textContent).toContain("indicadores oficiais");
    expect(container.textContent).not.toContain("Shopify");
  });

  it("Shopify não é apresentado como indicador oficial", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "shopify", provider_label: "Shopify", connected: true,
        status: "ok", kpi_source: "shopify_read_model", official_kpis: false,
      },
    };
    await renderIntelligence();
    const badge = container.querySelector('[data-testid="intel-commerce-provider"]');
    expect(badge?.textContent).toContain("Shopify");
    expect(badge?.textContent).not.toContain("indicadores oficiais");
  });

  it("duas plataformas ativas geram aviso em vez de escolha silenciosa", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true, status: "ok",
        kpi_source: "fbits_dashboard", official_kpis: true,
        ambiguous: true, active_providers: ["fbits", "shopify"],
      },
    };
    await renderIntelligence();
    expect(container.textContent).toContain("Há mais de uma plataforma de vendas ativa");
  });

  it("sem pesquisa externa configurada, nenhuma seção de mercado ou creators é renderizada", async () => {
    state.snapshot = {
      ...snapshot,
      external_research: {
        status: "not_configured", provider: null,
        market_signals: [], content_references: [], ugc_creators: [],
      },
    };
    await renderIntelligence();
    expect(container.querySelector('[data-testid="intel-market"]')).toBeNull();
    expect(container.querySelector('[data-testid="intel-creators"]')).toBeNull();
    expect(container.textContent).not.toContain("Mercado agora");
    expect(container.textContent).not.toContain("Creators e UGC");
  });

  it("sem o bloco de pesquisa externa, a página continua funcionando", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("Receita cresceu no período.");
    expect(container.querySelector('[data-testid="intel-market"]')).toBeNull();
  });

  it("com itens reais, exibe creators com fonte e sem recomendar contratação", async () => {
    state.snapshot = {
      ...snapshot,
      external_research: {
        status: "ok", provider: "provider-real",
        market_signals: [], content_references: [], ugc_creators: [researchItem],
      },
    };
    await renderIntelligence();
    const section = container.querySelector('[data-testid="intel-creators"]');
    expect(section?.textContent).toContain("@perfil");
    expect(section?.textContent).toContain("Creator para avaliar");
    expect(section?.querySelector("a")?.getAttribute("href")).toBe("https://exemplo/post");
    // O ITEM mostra evidência, nunca uma decisão de contratação.
    const itemText = section?.querySelector("a")?.textContent || "";
    expect(itemText).not.toMatch(/contrate|contrata/i);
    expect(container.textContent).toContain("A escolha de quem contratar é sempre sua");
  });

  it("status unavailable não renderiza seção externa", async () => {
    state.snapshot = {
      ...snapshot,
      external_research: {
        status: "unavailable", provider: "provider-real",
        market_signals: [researchItem], content_references: [], ugc_creators: [],
      },
    };
    await renderIntelligence();
    expect(container.querySelector('[data-testid="intel-market"]')).toBeNull();
  });
});

describe("Intelligence — hierarquia de decisão", () => {
  it("destaca no máximo 3 movimentos, com fato, importância e ação", async () => {
    await renderIntelligence();
    const section = container.querySelector('[data-testid="intel-movements"]');
    expect(section).not.toBeNull();
    expect(section?.querySelectorAll(".intelMovement")).toHaveLength(3);
    expect(section?.textContent).toContain("3 movimentos que merecem sua atenção");
    const first = section?.querySelector(".intelMovement");
    expect(first?.textContent).toContain("O que aconteceu");
    expect(first?.textContent).toContain("Por que importa");
    expect(first?.textContent).toContain("O que fazer");
  });

  it("risco aparece antes de leitura positiva na ordem dos movimentos", async () => {
    await renderIntelligence();
    const titles = [...container.querySelectorAll('[data-testid="intel-movements"] .intelMovement h3')]
      .map((el) => el.textContent);
    expect(titles[0]).toBe("CPA subindo");
  });

  it("hipótese e fato ficam visualmente distintos, sem hipótese vendida como fato", async () => {
    await renderIntelligence();
    const badges = [...container.querySelectorAll('[data-testid="intel-movements"] .intelInsightBadge')]
      .map((el) => el.className);
    expect(badges.some((name) => name.includes("is-fact"))).toBe(true);
    expect(badges.some((name) => name.includes("is-interpretation"))).toBe(true);
    expect(badges.some((name) => name.includes("is-recommendation"))).toBe(true);
  });

  it("oportunidades aterradas aparecem em seção própria, sem repetir o destaque", async () => {
    // Análise mais cheia: com só três insights, as oportunidades sobem todas
    // para os movimentos — e aí a seção não existe, por desenho.
    const base = {
      metric_ids: ["spend"], sources: ["meta_ads"],
      impact: "high" as const, confidence: "high" as const,
      reason: "Motivo observado.",
    };
    state.analysis = {
      ...analysis,
      analysis: {
        ...analysis.analysis,
        insights: [
          ...analysis.analysis.insights,
          { ...base, category: "risk" as const, title: "Frete encarecendo", interpretation: "Custo de entrega subiu.", action: "Revisar tabela." },
          { ...base, category: "attention" as const, title: "Estoque concentrado", interpretation: "Poucos SKUs sustentam a receita.", action: "Ampliar mix." },
        ],
      },
    };
    await renderIntelligence();
    const movements = container.querySelector('[data-testid="intel-movements"]');
    const opportunities = container.querySelector('[data-testid="intel-opportunities"]');
    expect(movements?.querySelectorAll(".intelMovement")).toHaveLength(3);
    expect(opportunities?.textContent).toContain("Público não explorado");
    // O que já está em destaque não é repetido abaixo.
    expect(opportunities?.textContent).not.toContain("CPA subindo");
  });

  it("ideias para testar saem das recomendações, com métrica e sem virar tarefa", async () => {
    await renderIntelligence();
    const section = container.querySelector('[data-testid="intel-ideas"]');
    expect(section?.textContent).toContain("Revisar campanha X");
    expect(section?.textContent).toContain("Métrica para acompanhar");
    expect(section?.textContent).toContain("Investimento");
    expect(section?.textContent).not.toMatch(/calendário|agendar|publicar|WhatsApp/i);
  });

  it("mostra fontes em nome humano e o frescor do dado", async () => {
    await renderIntelligence();
    const note = container.querySelector('[data-testid="intel-source-note"]');
    expect(note?.textContent).toContain("Meta Ads");
    // Fonte conectada sem dado no período não é anunciada como fonte.
    expect(note?.textContent).not.toContain("Google Ads");
    expect(note?.textContent).toContain("atualizado");
  });

  it("FBITS em fallback não é apresentado como indicador oficial", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true,
        status: "ok", kpi_source: "fbits_orders_fallback", official_kpis: false,
      },
    };
    await renderIntelligence();
    const badge = container.querySelector('[data-testid="intel-commerce-provider"]');
    expect(badge?.textContent).toContain("FBITS/Wake");
    expect(badge?.textContent).not.toContain("indicadores oficiais");
  });

  it("sem contexto da marca, gestão recebe convite discreto", async () => {
    state.snapshot = { ...snapshot, business_context: { available: false, context: {} } };
    await renderIntelligence(true);
    expect(container.querySelector('[data-testid="intel-context-cta"]')?.textContent)
      .toContain("Adicionar contexto da marca");
  });

  it("viewer não recebe convite para editar contexto", async () => {
    state.snapshot = { ...snapshot, business_context: { available: false, context: {} } };
    await renderIntelligence(false);
    expect(container.querySelector('[data-testid="intel-context-cta"]')).toBeNull();
  });

  it("com contexto preenchido, o convite desaparece", async () => {
    state.snapshot = {
      ...snapshot,
      business_context: { available: true, context: { segment: "Vinhos" } },
    };
    await renderIntelligence(true);
    expect(container.querySelector('[data-testid="intel-context-cta"]')).toBeNull();
  });

  it("sem insights, nenhuma seção de prioridade é inventada", async () => {
    state.analysis = {
      ...analysis,
      analysis: { ...analysis.analysis, insights: [], actions: [] },
    };
    await renderIntelligence();
    expect(container.querySelector('[data-testid="intel-movements"]')).toBeNull();
    expect(container.querySelector('[data-testid="intel-opportunities"]')).toBeNull();
    expect(container.querySelector('[data-testid="intel-ideas"]')).toBeNull();
  });
});
