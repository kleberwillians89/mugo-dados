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
  sources: [{ id: "meta_ads", label: "Meta Ads", status: "available" as const, connected: true, data_points: 30, covered_days: 30, last_sync_at: "2026-08-31T12:00:00Z" }],
  quality: { score: 90, status: "good" as const, available_sources: 2, total_sources: 2, errors: 0, message: "ok" },
  last_sync_at: "2026-08-31T12:00:00Z",
  metrics: analysis.metrics_snapshot,
  crossings: [],
  top_campaigns: [],
};

vi.mock("../app/api", () => ({
  getIntelligenceContext: vi.fn(async () => ({ ok: true, snapshot })),
  getLatestIntelligenceAnalysis: vi.fn(async () => ({ ok: true, provider_configured: true, analysis })),
  getIntelligenceHistory: vi.fn(async () => ({ ok: true, items: [analysis] })),
  generateIntelligenceAnalysis: vi.fn(async () => ({ ok: true, provider_configured: true, status: "completed", snapshot, analysis })),
  askIntelligence: vi.fn(),
}));

import Intelligence from "./Intelligence";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function renderIntelligence() {
  await act(async () => {
    root.render(<Intelligence onLogout={() => {}} />);
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
});
