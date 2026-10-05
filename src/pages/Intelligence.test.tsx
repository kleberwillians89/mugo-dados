// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({
  period: { start: "2026-08-01", end: "2026-08-31" },
  clientId: "amalie",
  clientName: "Amalie",
}));

vi.mock("../app/activeClient", () => ({
  getActiveClientId: () => mocks.clientId,
  getActiveClientName: () => mocks.clientName,
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
  /** Falhas simuladas por teste (o mock da api é inline neste arquivo). */
  contextError: null as Error | null,
  /** Backend inacessível: as três leituras falham, como no timeout real. */
  readError: null as Error | null,
  generateError: null as Error | null,
};

vi.mock("../app/api", () => ({
  getIntelligenceContext: vi.fn(async () => {
    if (state.readError) throw state.readError;
    if (state.contextError) throw state.contextError;
    return { ok: true, snapshot: state.snapshot };
  }),
  getLatestIntelligenceAnalysis: vi.fn(async () => {
    if (state.readError) throw state.readError;
    return { ok: true, provider_configured: true, analysis: state.analysis };
  }),
  getIntelligenceHistory: vi.fn(async () => {
    if (state.readError) throw state.readError;
    return { ok: true, items: [state.analysis] };
  }),
  generateIntelligenceAnalysis: vi.fn(async () => {
    if (state.generateError) throw state.generateError;
    return { ok: true, provider_configured: true, status: "completed", snapshot: state.snapshot, analysis: state.analysis };
  }),
  askIntelligence: vi.fn(),
}));

import Intelligence from "./Intelligence";
import { askIntelligence, generateIntelligenceAnalysis } from "../app/api";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  mocks.clientId = "amalie";
  mocks.clientName = "Amalie";
  vi.mocked(askIntelligence).mockReset();
  state.snapshot = snapshot;
  state.analysis = analysis;
  mocks.period = { start: "2026-08-01", end: "2026-08-31" };
  state.contextError = null;
  state.readError = null;
  state.generateError = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function renderIntelligence(canEditBusinessContext = true) {
  await act(async () => {
    root.render(<Intelligence onLogout={() => {}} canEditBusinessContext={canEditBusinessContext} />);
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

  it("abre com o resumo do momento, curto e no topo", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("Resumo");
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    // Primeira dobra é leitura, não arquitetura de providers.
    const moment = container.querySelector(".intelMoment");
    expect(moment?.textContent).not.toMatch(/Meta Ads|Google Ads|FBITS/);
  });

  it("mostra a fonte de cada métrica de evidência", async () => {
    await renderIntelligence();
    expect(container.textContent).toContain("Meta Ads");
  });

  it("não mostra status técnico de fonte nem fileira de chips no topo", async () => {
    await renderIntelligence();
    expect(container.textContent).not.toContain("connected_no_data");
    expect(container.querySelector(".intelSourceBar")).toBeNull();
    // Fontes viram uma linha discreta no fim.
    const sources = container.querySelector('[data-testid="intel-sources"]');
    expect(sources?.querySelector(".intelSourcesList")?.textContent).toBe("Meta Ads");
    expect(container.querySelector(".intelHeader")?.textContent).not.toContain("Meta Ads");
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

  it("a plataforma de vendas aparece por nome público, sem jargão interno", async () => {
    state.snapshot = {
      ...snapshot,
      sources: [...snapshot.sources, { id: "commerce", label: "E-commerce", status: "available" as const, connected: true, data_points: 30, covered_days: 30, last_sync_at: "2026-08-31T12:00:00Z" }],
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true,
        status: "ok", kpi_source: "fbits_dashboard", official_kpis: true,
      },
    };
    await renderIntelligence();
    const sources = container.querySelector('[data-testid="intel-sources"]');
    expect(sources?.querySelector(".intelSourcesList")?.textContent).toContain("FBITS");
    // Sem "/Wake", sem read_model, sem nome de fallback técnico.
    expect(container.textContent).not.toContain("FBITS/Wake");
    expect(container.textContent).not.toContain("read_model");
    expect(container.textContent).not.toContain("Shopify");
    // KPI oficial: nenhuma ressalva de confiança.
    expect(container.querySelector('[data-testid="intel-commerce-note"]')).toBeNull();
  });

  it("Shopify aparece com o próprio nome e sem termo técnico", async () => {
    state.snapshot = {
      ...snapshot,
      sources: [...snapshot.sources, { id: "commerce", label: "E-commerce", status: "available" as const, connected: true, data_points: 30, covered_days: 30, last_sync_at: "2026-08-31T12:00:00Z" }],
      commerce_context: {
        provider: "shopify", provider_label: "Shopify", connected: true,
        status: "ok", kpi_source: "shopify_read_model", official_kpis: false,
      },
    };
    await renderIntelligence();
    expect(container.querySelector(".intelSourcesList")?.textContent).toContain("Shopify");
    expect(container.textContent).not.toContain("shopify_read_model");
  });

  it("duas plataformas conectadas são avisadas discretamente, sem lista técnica", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true, status: "ok",
        kpi_source: "fbits_dashboard", official_kpis: true,
        ambiguous: true, active_providers: ["fbits", "shopify"],
      },
    };
    await renderIntelligence();
    const sources = container.querySelector('[data-testid="intel-sources"]');
    expect(sources?.textContent).toContain("mais de uma plataforma de vendas conectada");
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

  it("FBITS em fallback vira ressalva humana, não jargão", async () => {
    state.snapshot = {
      ...snapshot,
      commerce_context: {
        provider: "fbits", provider_label: "FBITS/Wake", connected: true,
        status: "ok", kpi_source: "fbits_orders_fallback", official_kpis: false,
      },
    };
    await renderIntelligence();
    const note = container.querySelector('[data-testid="intel-commerce-note"]');
    expect(note?.textContent).toContain("podem diferir do painel da loja");
    expect(container.textContent).not.toContain("fallback");
    expect(container.textContent).not.toContain("fbits_orders_fallback");
  });

  it("sem contexto da marca, gestão recebe convite discreto", async () => {
    state.snapshot = { ...snapshot, business_context: { available: false, context: {} } };
    await renderIntelligence(true);
    const cta = container.querySelector('[data-testid="intel-context-cta"]');
    expect(cta?.textContent).toContain("adicionando contexto estratégico");
    // Linha discreta, não cartão dominante.
    expect(cta?.tagName).toBe("P");
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

describe("Intelligence — estados da leitura", () => {
  it("sem análise, estado vazio compacto com ação de gerar", async () => {
    state.analysis = { ...analysis, status: "pending", analysis: null };
    await renderIntelligence(true);
    const empty = container.querySelector('[data-testid="intel-empty"]');
    expect(empty?.textContent).toContain("O que você quer entender?");
    expect([...container.querySelectorAll("button")].map((el) => el.textContent)).toContain("Gerar análise");
    // Sem hero gigante e sem seções de prioridade vazias.
    expect(container.querySelector(".intelExecutive")).toBeNull();
    expect(container.querySelector('[data-testid="intel-movements"]')).toBeNull();
  });

  it("viewer sem análise gera a primeira leitura do próprio tenant", async () => {
    // Regra mudou nesta release: gerar a análise estruturada é permitido a
    // qualquer membro, viewer incluído.
    state.analysis = { ...analysis, status: "pending", analysis: null };
    await renderIntelligence(false);
    expect(container.querySelector('[data-testid="intel-empty"]')).not.toBeNull();
    expect(container.textContent).not.toContain("Peça a um administrador");
    expect(container.querySelector('[data-testid="intel-generate-empty"]')).not.toBeNull();
  });

  it("erro com análise anterior preserva a leitura e avisa discretamente", async () => {
    await renderIntelligence();
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    state.generateError = new Error("Falha ao gerar");
    await act(async () => {
      [...container.querySelectorAll("button")].find((el) => el.textContent === "Gerar nova análise")?.click();
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector('[data-testid="intel-stale-warning"]')?.textContent)
      .toContain("A última análise válida continua disponível");
    // Last-known-good: a análise não foi apagada.
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    expect(container.querySelector('[data-testid="intel-error"]')).toBeNull();
  });

  it("erro sem nenhuma análise mostra erro compacto com nova tentativa", async () => {
    // Período inédito: sem última leitura válida em cache para preservar.
    mocks.period = { start: "2026-01-01", end: "2026-01-31" };
    state.analysis = { ...analysis, status: "pending", analysis: null };
    state.readError = new Error("Backend fora");
    await renderIntelligence(true);
    const errorBox = container.querySelector('[data-testid="intel-error"]');
    expect(errorBox?.textContent).toContain("Não foi possível concluir esta análise.");
    expect(errorBox?.querySelector("button")?.textContent).toBe("Tentar novamente");
    // Erro compacto, não página destruída.
    expect(container.querySelector(".intelHeader")).not.toBeNull();
  });

  it("não expõe detalhe técnico do erro ao cliente", async () => {
    mocks.period = { start: "2026-02-01", end: "2026-02-28" };
    state.analysis = { ...analysis, status: "pending", analysis: null };
    state.readError = new Error("INTELLIGENCE_CONTEXT_ERROR: traceback");
    await renderIntelligence(true);
    expect(container.textContent).not.toContain("traceback");
    expect(container.textContent).not.toContain("INTELLIGENCE_CONTEXT_ERROR");
  });

  it("falha de uma leitura só não vira erro: a análise anterior continua", async () => {
    state.contextError = new Error("Contexto indisponível");
    await renderIntelligence(true);
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    expect(container.querySelector('[data-testid="intel-error"]')).toBeNull();
  });

  it("cobertura de fontes é dita em linguagem humana, não como nota de qualidade", async () => {
    await renderIntelligence();
    expect(container.querySelector('[data-testid="intel-sources"]')?.textContent)
      .toContain("2 de 2 fontes com dados no período");
    expect(container.querySelector(".intelHeader")?.textContent).not.toContain("Qualidade");
    expect(container.querySelector(".intelHeader")?.textContent).not.toContain("%");
  });
});


describe("Intelligence — abrir com o que já existe e atualizar com segurança", () => {
  async function api() {
    return await import("../app/api");
  }

  beforeEach(() => {
    // Cada caso decide se quer cache; o padrão é começar limpo.
    window.sessionStorage.clear();
  });

  it("distingue frescor do dado e frescor da análise", async () => {
    await renderIntelligence();
    const meta = container.querySelector(".intelHeaderMeta")?.textContent || "";
    expect(meta).toContain("Dados atualizados");
    expect(meta).toContain("Análise gerada em");
  });

  it("viewer tem os dois botões, distintos", async () => {
    await renderIntelligence(false);
    const labels = [...container.querySelectorAll("button")].map((el) => el.textContent);
    expect(labels).toContain("Atualizar dados");
    expect(labels).toContain("Gerar nova análise");
    // O CTA de contexto estratégico continua administrativo.
    expect(container.querySelector('[data-testid="intel-context-cta"]')).toBeNull();
  });

  it("Atualizar dados relê as fontes persistidas e NUNCA chama a IA", async () => {
    const mod = await api();
    await renderIntelligence(false);
    const before = vi.mocked(mod.getLatestIntelligenceAnalysis).mock.calls.length;
    vi.mocked(mod.generateIntelligenceAnalysis).mockClear();

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-refresh-data"]')?.click();
    });
    await act(async () => Promise.resolve());

    expect(vi.mocked(mod.getLatestIntelligenceAnalysis).mock.calls.length).toBeGreaterThan(before);
    // O ponto central: revalidar não é gerar.
    expect(mod.generateIntelligenceAnalysis).not.toHaveBeenCalled();
    expect(mod.askIntelligence).not.toHaveBeenCalled();
  });

  it("o cooldown desabilita o botão logo após o clique", async () => {
    await renderIntelligence(false);
    const button = () => container.querySelector<HTMLButtonElement>('[data-testid="intel-refresh-data"]');
    expect(button()?.disabled).toBe(false);
    await act(async () => {
      button()?.click();
    });
    // Deixa a revalidação terminar: o que mantém o botão travado agora é o
    // cooldown, não o estado "Atualizando...".
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());
    expect(button()?.textContent).toBe("Atualizar dados");
    expect(button()?.disabled).toBe(true);
    expect(container.textContent).toContain("Aguarde");
  });

  it("falha ao atualizar não apaga a análise que está na tela", async () => {
    await renderIntelligence(false);
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    state.readError = new Error("Rede indisponível");
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-refresh-data"]')?.click();
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
  });

  it("com conteúdo persistido, reabrir não mostra skeleton", async () => {
    // Primeira visita grava o último estado válido.
    await renderIntelligence(false);
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    await act(async () => root.unmount());
    container.remove();

    // Segunda visita: o backend demora, mas a tela já abre com conteúdo.
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<Intelligence onLogout={() => {}} canEditBusinessContext={false} />);
    });
    expect(container.querySelector(".intelSkeletonMetrics")).toBeNull();
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());
  });

  it("o último estado válido fica em sessionStorage, não só em memória", async () => {
    // Cache em memória morre no reload e a tela volta ao skeleton; é por isso
    // que a persistência precisa ser verificada diretamente.
    await renderIntelligence(false);
    const keys = Object.keys(window.sessionStorage).filter((key) => key.includes("intelligence-workspace"));
    expect(keys).toHaveLength(1);
    const stored = JSON.parse(window.sessionStorage.getItem(keys[0]) || "{}");
    expect(stored.value?.analysis?.id).toBe(analysis.id);
    expect(stored.value?.refreshedAt).toBeTruthy();
  });

  it("avisa discretamente quando os dados são mais novos que a análise", async () => {
    state.snapshot = { ...snapshot, last_sync_at: "2026-09-02T12:00:00Z" };
    await renderIntelligence(false);
    const notice = container.querySelector('[data-testid="intel-fresher-data"]');
    expect(notice?.textContent).toContain("Há dados mais recentes disponíveis");
    // Com o aviso na tela, o viewer tem como agir: gerar a análise nova.
    expect(container.querySelector('[data-testid="intel-generate"]')).not.toBeNull();
  });

  it("sem dados mais novos, nenhum aviso aparece", async () => {
    await renderIntelligence(false);
    expect(container.querySelector('[data-testid="intel-fresher-data"]')).toBeNull();
  });
});


describe("Intelligence — gerar análise sem perder a anterior", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  async function api() {
    return await import("../app/api");
  }

  it("a análise anterior continua inteira enquanto a nova é gerada", async () => {
    const mod = await api();
    let release: (() => void) | null = null;
    vi.mocked(mod.generateIntelligenceAnalysis).mockImplementationOnce(
      () => new Promise((resolve) => {
        release = () => resolve({
          ok: true, provider_configured: true, status: "completed",
          snapshot: state.snapshot, analysis: { ...analysis, completed_at: "2026-09-05T10:00:00Z" },
        } as never);
      }),
    );
    await renderIntelligence(false);
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-generate"]')?.click();
    });

    // Durante a geração: conteúdo intacto, nenhum skeleton, botão em estado.
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    expect(container.querySelector(".intelSkeletonMetrics")).toBeNull();
    expect(container.querySelector('[data-testid="intel-generate"]')?.textContent).toBe("Gerando análise...");

    await act(async () => {
      release?.();
      await Promise.resolve();
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
  });

  it("clique duplo não dispara duas gerações", async () => {
    const mod = await api();
    vi.mocked(mod.generateIntelligenceAnalysis).mockClear();
    await renderIntelligence(false);
    const button = () => container.querySelector<HTMLButtonElement>('[data-testid="intel-generate"]');
    await act(async () => {
      button()?.click();
      button()?.click();
      button()?.click();
    });
    await act(async () => Promise.resolve());
    expect(vi.mocked(mod.generateIntelligenceAnalysis).mock.calls.length).toBe(1);
  });

  it("falha da IA preserva a análise anterior e avisa discretamente", async () => {
    await renderIntelligence(false);
    state.generateError = new Error("Provedor indisponível");
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-generate"]')?.click();
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    expect(container.querySelector('[data-testid="intel-stale-warning"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="intel-error"]')).toBeNull();
    expect(container.querySelector(".intelSkeletonMetrics")).toBeNull();
  });

  it("sucesso substitui a análise e avança o frescor da análise", async () => {
    const mod = await api();
    vi.mocked(mod.generateIntelligenceAnalysis).mockResolvedValueOnce({
      ok: true, provider_configured: true, status: "completed",
      snapshot: state.snapshot,
      analysis: {
        ...analysis,
        id: "an-2",
        completed_at: "2026-09-05T10:00:00Z",
        analysis: {
          ...analysis.analysis,
          executive: { ...analysis.analysis!.executive, overall: "Leitura nova do período." },
        },
      },
    } as never);
    await renderIntelligence(false);
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-generate"]')?.click();
    });
    await act(async () => Promise.resolve());
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Leitura nova do período.");
    expect(container.querySelector(".intelHeaderMeta")?.textContent).toContain("Análise gerada em");
  });

  it("Atualizar dados segue sem chamar a IA depois da mudança", async () => {
    const mod = await api();
    vi.mocked(mod.generateIntelligenceAnalysis).mockClear();
    await renderIntelligence(false);
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-refresh-data"]')?.click();
    });
    await act(async () => Promise.resolve());
    expect(mod.generateIntelligenceAnalysis).not.toHaveBeenCalled();
  });

  it("Gerar nova análise é o único caminho que chama a IA", async () => {
    const mod = await api();
    vi.mocked(mod.generateIntelligenceAnalysis).mockClear();
    await renderIntelligence(false);
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="intel-generate"]')?.click();
    });
    await act(async () => Promise.resolve());
    expect(mod.generateIntelligenceAnalysis).toHaveBeenCalledTimes(1);
  });
});

function conversationReply(directAnswer = "O investimento aumentou no período.", structured = true): Awaited<ReturnType<typeof askIntelligence>> {
  const message = { period_start: "2026-08-01", period_end: "2026-08-31", sources: [], created_at: "2026-08-31T12:00:00Z" };
  return {
    ok: true, conversation_id: "conversation-1", snapshot,
    user_message: { ...message, id: "user-1", role: "user", content: { question: "Como estão minhas vendas?" } },
    assistant_message: { ...message, id: "answer-1", role: "assistant", content: {
      direct_answer: directAnswer,
      ...(structured ? { metric_ids: ["spend"], evidence: ["O investimento foi de R$ 1.000."], attention_points: ["Compare períodos com a mesma cobertura."], recommendations: ["Revise o orçamento."], next_steps: ["Acompanhe a próxima semana."] } : {}),
    } },
  } as unknown as Awaited<ReturnType<typeof askIntelligence>>;
}

async function enterQuestion(value: string) {
  await act(async () => {
    const input = container.querySelector<HTMLTextAreaElement>("#intel-question")!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function sendQuestion() {
  await act(async () => {
    container.querySelector<HTMLFormElement>(".intelAskForm")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("Intelligence — analista executivo", () => {
  it("abre com título, contexto discreto e seis sugestões sem gerar IA automaticamente", async () => {
    state.analysis = { ...analysis, status: "pending", analysis: null };
    await renderIntelligence(false);
    expect(container.querySelector("h1")?.textContent).toBe("Inteligência");
    expect(container.textContent).toContain("Entenda o que está acontecendo no seu negócio e onde agir.");
    expect(container.querySelectorAll(".intelQuestionSuggestions button")).toHaveLength(6);
    await act(async () => { container.querySelector<HTMLButtonElement>(".intelQuestionSuggestions button")!.click(); });
    expect(container.querySelector<HTMLTextAreaElement>("#intel-question")?.value).toBe("Como está meu desempenho este mês?");
    expect(askIntelligence).not.toHaveBeenCalled();
    expect(document.activeElement?.id).toBe("intel-question");
  });

  it("viewer envia pelo fluxo existente e recebe resposta editorial com dados reais da resposta", async () => {
    vi.mocked(askIntelligence).mockResolvedValue(conversationReply());
    await renderIntelligence(false);
    await enterQuestion("Como estão minhas vendas?");
    await sendQuestion();
    expect(askIntelligence).toHaveBeenCalledWith({ question: "Como estão minhas vendas?", conversation_id: null, start: "2026-08-01", end: "2026-08-31" }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    const answer = container.querySelector(".intelMessage.is-assistant")!;
    for (const label of ["Resumo", "Números importantes", "Leitura", "Próximos passos", "Revise o orçamento."]) expect(answer.textContent).toContain(label);
    expect(answer.querySelector(".intelEvidence")?.textContent).toContain("1.000");
    expect(container.querySelector(".intelAskForm")?.parentElement).toBe(container.querySelector(".intelligencePage"));
  });

  it("mostra processamento real e mantém a análise anterior", async () => {
    let finish!: (result: Awaited<ReturnType<typeof askIntelligence>>) => void;
    vi.mocked(askIntelligence).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await renderIntelligence();
    await enterQuestion("Explique o período"); await sendQuestion();
    expect(container.querySelector(".intelProcessing")?.textContent).toContain("Analisando os dados de Amalie...");
    expect(container.querySelector(".intelMomentLead")?.textContent).toBe("Receita cresceu no período.");
    expect(container.querySelector<HTMLButtonElement>(".intelAskForm button")?.disabled).toBe(true);
    await act(async () => { finish(conversationReply()); });
    expect(container.querySelector(".intelProcessing")).toBeNull();
  });

  it("texto sem estrutura não ganha métricas ou recomendações inventadas", async () => {
    vi.mocked(askIntelligence).mockResolvedValue(conversationReply("Leitura simples.\nSem números adicionais.", false));
    await renderIntelligence(); await enterQuestion("Uma leitura simples"); await sendQuestion();
    const answer = container.querySelector(".intelMessage.is-assistant")!;
    expect(answer.querySelector("h3")?.textContent).toBe("Leitura simples.\nSem números adicionais.");
    expect(answer.querySelector(".intelAnswerMetrics")).toBeNull();
    expect(answer.querySelector(".intelNextSteps")).toBeNull();
  });

  it("oferece três follow-ups e mantém o identificador da conversa ao continuar", async () => {
    vi.mocked(askIntelligence).mockResolvedValue(conversationReply());
    await renderIntelligence(); await enterQuestion("Como estão minhas vendas?"); await sendQuestion();
    const suggestions = container.querySelectorAll<HTMLButtonElement>(".intelFollowUps button");
    expect(suggestions).toHaveLength(3);
    await act(async () => { suggestions[0].click(); });
    expect(askIntelligence).toHaveBeenCalledTimes(1);
    expect(container.querySelector<HTMLTextAreaElement>("#intel-question")?.value).toBe("Por que isso aconteceu?");
    await sendQuestion();
    expect(vi.mocked(askIntelligence).mock.calls[1][0].conversation_id).toBe("conversation-1");
  });

  it("Enter envia e Shift+Enter permite quebra sem envio", async () => {
    vi.mocked(askIntelligence).mockResolvedValue(conversationReply());
    await renderIntelligence(); await enterQuestion("Explique os dados");
    const input = container.querySelector<HTMLTextAreaElement>("#intel-question")!;
    const shift = new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true, cancelable: true });
    await act(async () => { input.dispatchEvent(shift); });
    expect(shift.defaultPrevented).toBe(false);
    expect(askIntelligence).not.toHaveBeenCalled();
    await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })); });
    expect(askIntelligence).toHaveBeenCalledOnce();
  });

  it("erro de pergunta é discreto e tentar novamente repete a pergunta, sem gerar análise", async () => {
    vi.mocked(askIntelligence).mockRejectedValueOnce(new Error("TRACEBACK_TESTE")).mockResolvedValue(conversationReply());
    await renderIntelligence(); vi.mocked(generateIntelligenceAnalysis).mockClear();
    await enterQuestion("Como estão minhas vendas?"); await sendQuestion();
    expect(container.textContent).toContain("Não foi possível concluir esta análise.");
    expect(container.textContent).not.toContain("TRACEBACK_TESTE");
    await act(async () => { [...container.querySelectorAll("button")].find((button) => button.textContent === "Tentar novamente")!.click(); });
    expect(askIntelligence).toHaveBeenCalledTimes(2);
    expect(generateIntelligenceAnalysis).not.toHaveBeenCalled();
    expect(container.querySelector(".intelMessage.is-assistant")).not.toBeNull();
  });

  it("trocar tenant remove a conversa anterior e preserva a leitura do novo tenant", async () => {
    vi.mocked(askIntelligence).mockResolvedValue(conversationReply("Resposta exclusiva da Amalie."));
    await renderIntelligence(); await enterQuestion("Como estão minhas vendas?"); await sendQuestion();
    mocks.clientId = "roove"; mocks.clientName = "Roove";
    state.snapshot = { ...snapshot, client: { id: "roove", name: "Roove" } };
    state.analysis = { ...analysis, client_id: "roove" };
    await renderIntelligence(false);
    expect(container.textContent).not.toContain("Resposta exclusiva da Amalie.");
    expect(container.querySelector(".intelHeaderMeta")?.textContent).toContain("Roove");
    expect(container.querySelectorAll(".intelMessage")).toHaveLength(0);
  });
});

describe("Intelligence — fechamento da apresentação", () => {
  it("retira versionamento e histórico visual sem retirar a análise e perguntas", async () => {
    await renderIntelligence(false);
    expect(container.textContent).not.toContain("Versionamento");
    expect(container.textContent).not.toContain("Histórico de análises");
    expect(container.textContent).toContain("Receita cresceu no período.");
    expect(container.querySelector(".intelAskForm")).not.toBeNull();
  });

  it("usa sincronização persistida e não renova freshness ao gerar análise", async () => {
    state.snapshot = { ...snapshot, last_sync_at: new Date(Date.now() - 10 * 60_000).toISOString() };
    await renderIntelligence(false);
    expect(container.querySelector(".intelHeaderMeta")?.textContent).toContain("há 10 min");
    const button = [...container.querySelectorAll("button")].find((el) => el.textContent === "Gerar nova análise")!;
    await act(async () => button.click());
    expect(container.querySelector(".intelHeaderMeta")?.textContent).toContain("há 10 min");
  });

  it("não anuncia freshness sem timestamp persistido", async () => {
    state.snapshot = { ...snapshot, last_sync_at: null };
    await renderIntelligence(false);
    expect(container.querySelector(".intelHeaderMeta")?.textContent).not.toContain("Dados atualizados");
  });

  it("traduz fontes internas somente na apresentação", async () => {
    state.snapshot = { ...snapshot, metrics: [{ ...analysis.metrics_snapshot[0], source: "shopify+paid_media" }] };
    state.analysis = { ...analysis, metrics_snapshot: state.snapshot.metrics,
      analysis: { ...analysis.analysis, insights: [{ ...analysis.analysis.insights[0], sources: ["ga4", "paid_media"] }] } };
    await renderIntelligence(false);
    expect(container.textContent).toContain("Loja virtual e mídia paga");
    expect(container.textContent).toContain("Google Analytics");
    expect(container.textContent).toContain("Mídia paga");
    expect(container.textContent).not.toContain("shopify+paid_media");
  });
});
