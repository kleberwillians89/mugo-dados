// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const state = vi.hoisted(() => ({
  role: "client_admin",
  paid: true,
  metaSource: true,
  integrations: true,
  readModel: "ok" as "ok" | "loading" | "error",
}));

// Os hooks reais devolvem referências memorizadas; os mocks também, senão
// os efeitos que dependem delas rodariam a cada render.
const stable = vi.hoisted(() => {
  const cache = new Map<string, unknown>();
  return <T,>(key: string, build: () => T): T => {
    const full = `${key}:${JSON.stringify(state)}`;
    if (!cache.has(full)) cache.set(full, build());
    return cache.get(full) as T;
  };
});

const refreshApi = vi.hoisted(() => ({ refreshProviderData: vi.fn(), refetch: vi.fn(), reloadSummary: vi.fn() }));
vi.mock("../app/api", async (original) => ({
  ...(await original<typeof import("../app/api")>()),
  ...refreshApi,
}));

vi.mock("../app/activeClient", () => ({
  getActiveClient: () => ({ id: "curavino", name: "Curavino", role: state.role }),
  getActiveClientId: () => "curavino",
  getActiveClientName: () => "Curavino",
  getActiveClientConfigurationWarning: () => null,
}));

vi.mock("../app/PeriodContext", () => ({
  usePeriod: () => ({
    period: { start: "2026-08-01", end: "2026-08-31" },
    periodDays: 31,
    setPresetPeriod: () => {},
    setCurrentMonthPeriod: () => {},
    setMonthPeriod: () => {},
    setDayPeriod: () => {},
  }),
}));

vi.mock("../app/connectionState", () => ({
  getActiveConnectionId: () => null,
  getSelectedConnectionId: () => "meta-auth",
}));

vi.mock("../app/DashboardDataContext", () => ({
  useDashboardSnapshot: () => stable("snapshot", () => ({
    snapshot: state.readModel === "ok" ? { daily: [], sources: [], campaigns: [], products: [] } : null,
    loading: state.readModel === "loading",
    error: state.readModel === "error" ? "Falha de leitura" : null,
    daily: [], sources: [], campaigns: [], refetch: refreshApi.refetch,
  })),
}));

vi.mock("../hooks/useClientIntegrations", () => ({
  default: () => stable("integrations", () => ({
    lastValidConnections: state.integrations ? [{
      provider: "meta", connection_id: "meta-auth", status: "connected", authorization_status: "valid", sync_status: null,
      account: { name: "Pessoa autorizada" },
      assets: {
        facebook_page_id: "516985944838234", facebook_page_name: "Página Curavino",
        instagram_account_id: "17841471880135733", instagram_account_name: "curavino",
        ad_account_id: "act_8024076734300108", ad_account_name: "Curavino Ads",
      },
      last_sync_at: null, last_successful_sync_at: null, last_error: null, updated_at: null,
    }] : [],
  })),
}));

vi.mock("../hooks/dashboard/useDashboardSummary", () => ({
  default: () => stable("summary", () => ({
    data: { dash: { ok: true, daily: [], period_totals: {} }, media: [], comments: [], commentsTotal: 0, topWords: [] },
    reloadSummary: refreshApi.reloadSummary,
    refreshingSummary: false,
    sectionLoading: { dash: false, media: false, comments: false, stories: false },
    sectionRefreshing: { dash: false, media: false, comments: false, stories: false },
    sectionErrors: { dash: null, media: null, comments: null, stories: null },
    sectionUpdatedAt: { dash: null, media: null, comments: null, stories: null },
  })),
}));

vi.mock("../hooks/dashboard/useDashboardMonthlyContent", () => ({
  default: () => stable("monthly", () => ({ monthlyRows: [], loadingMonthly: false, refreshingMonthly: false, monthlyError: null, monthlyUpdatedAt: null })),
}));

const paidTotals = vi.hoisted(() => ({ spend: 18_400, revenue: 50_000, conversions: 327, impressions: 900_000, reach: 400_000, clicks: 20_000, cpc: 0.92, cpm: 20.4, ctr: 2.2, roas: 2.72 }));

vi.mock("../hooks/dashboard/useDashboardPaid", () => ({
  default: () => stable("paid", () => ({
    paidData: state.paid
      ? { ok: true, has_data: true, totals: paidTotals, daily: [], row_count: 31, top_creatives: [], manager_metrics: { link_clicks: 12_000, video_views: 30_000 } }
      : { ok: true, has_data: false, totals: { ...paidTotals, spend: null, revenue: null, conversions: null }, daily: [], row_count: 31, top_creatives: [] },
    loadingPaid: false,
    refreshingPaid: false,
    paidError: null,
    paidUpdatedAt: null,
  })),
}));

vi.mock("../hooks/dashboard/useExecutiveDashboard", () => ({
  default: () => stable("executive", () => ({
    executiveData: {
      meta: { connected: state.metaSource, last_success_at: state.metaSource && state.paid ? "2026-08-31T12:00:00Z" : null },
      instagram: { connected: false, last_success_at: null },
      shopify: { connected: false },
      daily: [],
    },
  })),
}));

vi.mock("../hooks/dashboard/useCampaignsRanking", () => ({
  default: () => stable("campaigns", () => ({ campaignsData: { campaigns: [] }, loadingCampaigns: false, campaignsError: null })),
}));

vi.mock("../components/dashboard/PerformanceChart", () => ({
  default: () => <div data-testid="performance-chart-stub" />,
}));

import Dashboard from "./Dashboard";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  refreshApi.refetch.mockReset();
  refreshApi.reloadSummary.mockReset();
  refreshApi.refetch.mockResolvedValue({ daily: [], sources: [], campaigns: [], products: [] });
  refreshApi.reloadSummary.mockResolvedValue({});
  refreshApi.refreshProviderData.mockReset();
  refreshApi.refreshProviderData.mockResolvedValue({ok:true});
  Object.assign(state, { role: "client_admin", paid: true, metaSource: true, integrations: true, readModel: "ok" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

async function render(canSync: boolean) {
  await act(async () => {
    root.render(<Dashboard isAuthenticated canSync={canSync} onOpenSetup={() => {}} />);
  });
  await act(async () => Promise.resolve());
}

describe("Meta — leitura editorial", () => {
  it("diz qual empresa, conexão e ativos estão em uso, e quanto foi investido", async () => {
    await render(true);
    expect(container.querySelector("h1")?.textContent).toBe("Meta");
    const assets = container.querySelector('[data-testid="meta-connection-assets"]');
    expect(assets?.textContent).toContain("Página Curavino");
    expect(assets?.textContent).toContain("@curavino");
    expect(assets?.textContent).toContain("Curavino Ads");
    // IDs técnicos só para agência.
    expect(assets?.textContent).not.toContain("act_8024076734300108");
    const hero = container.querySelector('[data-testid="meta-ads-spend"]');
    expect(hero?.querySelector("data")?.getAttribute("value")).toBe("18400");
    expect(hero?.textContent).toContain("investidos em Meta Ads, com 327 compras atribuídas no período");
  });

  it("agência vê os IDs dos ativos de forma discreta", async () => {
    state.role = "agency_admin";
    await render(true);
    expect(container.querySelector('[data-testid="meta-connection-assets"]')?.textContent).toContain("act_8024076734300108");
  });

  it("viewer vê Atualizar dados", async () => {
    state.role = "viewer";
    await render(false);
    expect([...container.querySelectorAll("button")].some((button) => button.textContent === "Atualizar dados")).toBe(true);
  });

  it("conectado e ainda não sincronizado não vira investimento zero", async () => {
    state.paid = false;
    await render(true);
    expect(container.querySelector('[data-testid="meta-ads-spend"]')).toBeNull();
    // Linguagem de cliente: estado vazio simples, sem jargão de sincronização.
    expect(container.textContent).toContain("Ainda não há dados de Meta Ads");
    expect(container.textContent).not.toMatch(/Aguardando sincronização|importação terminar/i);
    expect(container.textContent).not.toContain("R$ 0");
  });

  it("falha de leitura do read model aparece como erro, nunca como Meta não conectada", async () => {
    Object.assign(state, { paid: false, metaSource: false, readModel: "error" });
    await render(true);
    expect(container.textContent).toContain("Não foi possível ler os dados da Meta");
    expect(container.textContent).not.toContain("Meta ainda não conectada");
    expect(container.textContent).not.toContain("Instagram conectado");
  });

  it("enquanto o read model carrega, mostra carregando e não 'conectado, aguardando'", async () => {
    Object.assign(state, { paid: false, metaSource: false, readModel: "loading" });
    await render(true);
    expect(container.textContent).toContain("Carregando Meta Ads...");
    expect(container.textContent).toContain("Carregando Instagram...");
    expect(container.textContent).not.toContain("Aguardando sincronização válida");
  });

  it("sem nenhuma conexão Meta, orienta a conectar em vez de mostrar números", async () => {
    Object.assign(state, { paid: false, metaSource: false, integrations: false });
    await render(true);
    expect(container.textContent).toContain("Meta ainda não conectada");
    expect(container.querySelector('[data-testid="meta-connection-assets"]')).toBeNull();
  });
});


it("viewer atualiza somente Meta, falha preserva cards e freshness", async () => {
  state.role = "viewer";
  await render(false);
  const card = container.querySelector('[data-testid="meta-ads-spend"]');
  expect(card).not.toBeNull();
  const header = container.querySelector(".ds-dateline")?.textContent;
  refreshApi.refreshProviderData.mockRejectedValue(new Error("indisponível"));
  await act(async () => {
    const action = [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizar dados");
    action?.dispatchEvent(new MouseEvent("click", {bubbles:true}));
  });
  expect(refreshApi.refreshProviderData).toHaveBeenCalledExactlyOnceWith("meta", {start:"2026-08-01",end:"2026-08-31"});
  expect(container.querySelector('[data-testid="meta-ads-spend"]')).toBe(card);
  expect(container.querySelector(".ds-dateline")?.textContent).toBe(header);
  expect(container.querySelector('[class*="skeleton"]')).toBeNull();
  expect(container.textContent).toContain("Mantendo a última leitura disponível");
});


it("Meta espera sync terminar antes da releitura e entrega snapshot novo ao resumo", async () => {
  let finish!: (value: unknown) => void;
  refreshApi.refreshProviderData.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  await render(true);
  await act(async () => { [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizar dados")!.click(); });
  expect(refreshApi.refetch).not.toHaveBeenCalled();
  expect(refreshApi.reloadSummary).not.toHaveBeenCalled();
  const fresh = { daily: [{ instagram_reach: 99 }], sources: [{ provider: "instagram", last_success_at: "fresh" }] };
  refreshApi.refetch.mockResolvedValue(fresh);
  await act(async () => { finish({ ok: true }); });
  expect(refreshApi.refetch).toHaveBeenCalledExactlyOnceWith({ afterCurrent: true });
  expect(refreshApi.reloadSummary).toHaveBeenCalledExactlyOnceWith({ snapshot: fresh, includeSecondary: true, loadStories: true });
});

it("Meta não anuncia sucesso quando a releitura falha", async () => {
  refreshApi.refetch.mockResolvedValue(null);
  await render(true);
  await act(async () => { [...container.querySelectorAll("button")].find((item) => item.textContent === "Atualizar dados")!.click(); });
  expect(refreshApi.reloadSummary).not.toHaveBeenCalled();
  expect(container.textContent).toContain("Mantendo a última leitura disponível");
});
