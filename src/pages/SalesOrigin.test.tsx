// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ getSalesByOrigin: vi.fn() }));
const active = vi.hoisted(() => ({ id: "roove" }));
vi.mock("../app/salesByOrigin", () => api);
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => active.id, getActiveClientName: () => "Roove" }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start: "2026-10-01", end: "2026-10-21" } }) }));
vi.mock("../components/Shell", () => ({ default: ({ children }: { children: React.ReactNode }) => React.createElement("div", null, children) }));
vi.mock("../components/data/PeriodSelector", () => ({ default: () => null }));

import SalesOrigin from "./SalesOrigin";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  api.getSalesByOrigin.mockReset();
  active.id = "roove";
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); }); };

const AVAILABLE = {
  ok: true, status: "available", provider: "shopify", period: { start: "2026-10-01", end: "2026-10-21" },
  attribution_model: "last_click_utm", attribution_model_label: "Último clique com UTM registrado pela loja",
  notes: ["Receita da loja por origem do pedido."],
  totals: { orders: 3, revenue: 200, average_ticket: 66.67, orders_with_origin: 2, orders_with_utm: 2, origin_coverage_percent: 66.67, utm_coverage_percent: 66.67 },
  channels: [
    { channel: "paid_social", label: "Mídia paga · redes sociais", orders: 2, revenue: 150, average_ticket: 75, share_of_revenue: 75 },
    { channel: "unknown", label: "Origem não identificada", orders: 1, revenue: 50, average_ticket: 50, share_of_revenue: 25 },
  ],
  campaigns: [{ channel: "paid_social", channel_label: "Mídia paga · redes sociais", source: "facebook", medium: "cpc", campaign: "bf_2026", orders: 2, revenue: 150, average_ticket: 75, share_of_revenue: 75 }],
};

describe("Página Origem das vendas", () => {
  it("mostra a empresa ativa, canais, campanhas e cobertura", async () => {
    api.getSalesByOrigin.mockResolvedValue(AVAILABLE);
    await act(async () => root.render(<SalesOrigin />));
    await flush();
    expect(api.getSalesByOrigin).toHaveBeenCalledWith("2026-10-01", "2026-10-21");
    const text = container.textContent || "";
    expect(text).toContain("Roove");
    expect(text).toContain("Origem das vendas");
    expect(text).toContain("Mídia paga · redes sociais");
    expect(text).toContain("Origem não identificada");
    expect(text).toContain("bf_2026");
    expect(text).toContain("facebook / cpc");
    expect(text).not.toContain("Leitura por campanha ainda parcial");
  });

  it("avisa quando poucos pedidos têm campanha", async () => {
    api.getSalesByOrigin.mockResolvedValue({ ...AVAILABLE, totals: { ...AVAILABLE.totals, utm_coverage_percent: 12 } });
    await act(async () => root.render(<SalesOrigin />));
    await flush();
    expect(container.textContent).toContain("Leitura por campanha ainda parcial");
  });

  it("descarta resposta de outra empresa quando a empresa ativa muda", async () => {
    let resolve: (value: unknown) => void = () => {};
    api.getSalesByOrigin.mockReturnValue(new Promise((done) => { resolve = done; }));
    await act(async () => root.render(<SalesOrigin />));
    active.id = "curavino";
    resolve(AVAILABLE);
    await flush();
    expect(container.textContent).not.toContain("bf_2026");
  });

  it("explica quando a empresa não tem loja conectada", async () => {
    api.getSalesByOrigin.mockResolvedValue({ ok: true, status: "not_connected", provider: null, totals: null, channels: [], campaigns: [], attribution_model: "", attribution_model_label: "", period: { start: "", end: "" } });
    await act(async () => root.render(<SalesOrigin />));
    await flush();
    expect(container.textContent).toContain("Nenhuma loja conectada");
  });
});
