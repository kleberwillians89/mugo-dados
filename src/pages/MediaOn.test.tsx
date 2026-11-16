// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "curavino", getActiveClientName: () => "Curavino" }));
vi.mock("../app/media", async (original) => ({ ...(await original<typeof import("../app/media")>()),
  getPlan: vi.fn(async () => ({ month: "2026-12-01", plan: null, elapsed_days: 0, days_in_month: 31, channels: [] })),
  listStrategies: vi.fn(async () => ({ strategies: [] })),
  generateStrategy: vi.fn(async () => { throw new Error("Sem dados de mídia ainda."); }),
}));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: unknown }) => children }));
vi.mock("../components/data/PageHeader", () => ({ default: () => null }));
vi.mock("../components/studio/BrandContextPanel", () => ({ default: () => null }));
vi.mock("../components/studio/MetaAdsPanel", () => ({ default: () => null }));

import * as media from "../app/media";
import MediaOn from "./MediaOn";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
afterEach(() => { host?.remove(); vi.clearAllMocks(); });

describe("Mídia On", () => {
  it("mês vazio: a equipe já abre com a IA gerando a estratégia (uma vez só)", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage />); });
    await act(async () => {});
    expect(media.generateStrategy).toHaveBeenCalledTimes(1);
    expect(vi.mocked(media.generateStrategy).mock.calls[0][0].objective).toBe("vendas");
    expect(host.textContent).toContain("Sem dados de mídia ainda.");
    act(() => root.unmount());
  });

  it("cliente (sem gestão) nunca gera sozinho", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage={false} />); });
    await act(async () => {});
    expect(media.generateStrategy).not.toHaveBeenCalled();
    act(() => root.unmount());
  });

  it("mantém parâmetros separados ao trocar entre os seis objetivos", async () => {
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage />); });
    await act(async () => {});
    vi.mocked(media.generateStrategy).mockClear();

    const button = (label: string) => Array.from(host.querySelectorAll("button")).find((el) => el.textContent?.startsWith(label)) as HTMLButtonElement;
    const type = async (input: HTMLInputElement, value: string) => act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Análise Técnica").click(); });
    await act(async () => { button("Leads").click(); });
    const leads = host.querySelector('[data-objective-parameter="target_leads"]') as HTMLInputElement;
    await type(leads, "250");
    await act(async () => { button("Tráfego").click(); });
    const clicks = host.querySelector('[data-objective-parameter="target_clicks"]') as HTMLInputElement;
    expect(clicks.value).toBe("");
    await type(clicks, "900");
    await act(async () => { button("Gerar estratégia").click(); });
    expect(media.generateStrategy).toHaveBeenLastCalledWith(expect.objectContaining({
      objective: "trafego", objective_parameters: { target_clicks: 900 },
    }));
    await act(async () => { button("Leads").click(); });
    expect((host.querySelector('[data-objective-parameter="target_leads"]') as HTMLInputElement).value).toBe("250");
    act(() => root.unmount());
  });

  it("abre na Visão Simples e alterna para a análise técnica sem nova geração nem perda de parâmetros", async () => {
    const scenario: media.Scenario = { key: "eficiencia", label: "Eficiência", budget: 1000, why: "Dados observados", allocation: { meta: 1000 },
      allocation_pct: { meta: 1 }, change_vs_current: { meta: 0 }, marginal_roas: 3,
      result: { channels: { meta: { spend: 1000, revenue: 5000, conversions: 50, clicks: 2000, impressions: 100000, roas: 5, cpa: 20, cpc: 0.5, cpm: 10 } },
        totals: { spend: 1000, revenue: 5000, conversions: 50, clicks: 2000, impressions: 100000, roas: 5, cpa: 20 } } };
    const recent = { spend: 1000, impressions: 100000, clicks: 2000, conversions: 50, revenue: 5000, cpm: 10, cpc: 0.5, ctr: 0.02, cpa: 20, roas: 5, conversion_rate: 0.025 };
    const strategy: media.SavedStrategy = { month: "2026-12", objective: "vendas", metric: "revenue", metric_label: "receita atribuída", days: 30,
      window: { start: "2026-10-01", end: "2026-10-30", days: 30 }, diagnosis: [{ channel: "meta", label: "Meta Ads", recent, previous: recent, window: recent,
        changes: { spend: 0, revenue: 0, roas: 0, cpa: 0, cpm: 0, ctr: 0, conversions: 0 }, confidence: "boa", days_with_spend: 30, monthly_spend: 1000, findings: [] }],
      store: {}, goal_revenue: null, margin: 0.4, curves: { meta: { revenue: { a: 1, b: 0.7, fit: "medida", r2: 0.8, points: 10 } } as media.Strategy["curves"]["meta"] },
      current_budget: 1000, scenario, scenarios: [scenario], recommended: "eficiencia", selected: "eficiencia", weeks: [], guardrails: [],
      campaigns: [{ channel: "meta", campaign: "Campanha A", action: "escalar", why: "ROAS acima da média", spend: 1000, conversions: 50, revenue: 5000, roas: 5, cpa: 20, share: 1, planned_budget: 1000 }],
      waste: 0, findings: [], method: "fixture", boosts: { pool: 0, share: 0, posts: [], note: null },
      narrative: { headline: "Leitura", thesis: "Leitura existente", channel_roles: [], campaign_notes: [], creative_guidance: [], risks: [], next_7_days: ["Acompanhar a campanha A."] } };
    vi.mocked(media.getPlan).mockResolvedValueOnce({ month: "2026-12", elapsed_days: 1, days_in_month: 31, channels: [], plan: {
      id: "plan-1", month: "2026-12", objective: "vendas", budget: 1000, allocation: { meta: 1000 }, scenario: "eficiencia", margin: 0.4,
      strategy, notes: null, status: "rascunho", updated_at: "2026-11-01T10:00:00Z",
    } });
    host = document.createElement("div"); document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => { root.render(<MediaOn canManage />); });
    await act(async () => {});
    expect(host.textContent).toContain("Seu marketing em 1 minuto");
    expect(vi.mocked(media.generateStrategy)).not.toHaveBeenCalled();

    const button = (label: string) => Array.from(host.querySelectorAll("button")).find((el) => el.textContent === label) as HTMLButtonElement;
    await act(async () => { button("Análise Técnica").click(); });
    const margin = Array.from(host.querySelectorAll("input")).find((input) => input.parentElement?.textContent?.includes("Margem de contribuição")) as HTMLInputElement;
    expect(margin.value).toBe("40");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(margin, "45");
      margin.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => { button("Visão Simples").click(); });
    await act(async () => { button("Análise Técnica").click(); });
    const restored = Array.from(host.querySelectorAll("input")).find((input) => input.parentElement?.textContent?.includes("Margem de contribuição")) as HTMLInputElement;
    expect(restored.value).toBe("45");
    expect(vi.mocked(media.generateStrategy)).not.toHaveBeenCalled();
    act(() => root.unmount());
  });
});
