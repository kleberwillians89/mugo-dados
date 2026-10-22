// @vitest-environment jsdom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({ getSalesByOrigin: vi.fn() }));
vi.mock("../app/salesByOrigin", () => api);
vi.mock("../app/activeClient", () => ({ getActiveClientId: () => "roove" }));
vi.mock("../app/PeriodContext", () => ({ usePeriod: () => ({ period: { start: "2026-10-01", end: "2026-10-21" } }) }));

import SalesByOriginPanel from "./SalesByOriginPanel";

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

beforeEach(() => {
  api.getSalesByOrigin.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

const flush = async () => { for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve(); }); };

describe("SalesByOriginPanel", () => {
  it("mostra canais, campanhas e cobertura de origem", async () => {
    api.getSalesByOrigin.mockResolvedValue({
      ok: true, status: "available", provider: "shopify", period: { start: "2026-10-01", end: "2026-10-21" },
      attribution_model: "last_click_utm", attribution_model_label: "Último clique com UTM registrado pela loja",
      notes: ["Receita da loja por origem do pedido."],
      totals: { orders: 3, revenue: 200, average_ticket: 66.67, orders_with_origin: 2, orders_with_utm: 2, origin_coverage_percent: 66.67, utm_coverage_percent: 66.67 },
      channels: [
        { channel: "paid_social", label: "Mídia paga · redes sociais", orders: 2, revenue: 150, average_ticket: 75, share_of_revenue: 75 },
        { channel: "unknown", label: "Origem não identificada", orders: 1, revenue: 50, average_ticket: 50, share_of_revenue: 25 },
      ],
      campaigns: [{ channel: "paid_social", channel_label: "Mídia paga · redes sociais", source: "facebook", medium: "cpc", campaign: "bf_2026", orders: 2, revenue: 150, average_ticket: 75, share_of_revenue: 75 }],
    });
    await act(async () => root.render(<SalesByOriginPanel />));
    await flush();
    expect(api.getSalesByOrigin).toHaveBeenCalledWith("2026-10-01", "2026-10-21");
    const text = container.textContent || "";
    expect(text).toContain("Mídia paga · redes sociais");
    expect(text).toContain("Origem não identificada");
    expect(text).toContain("bf_2026");
    expect(text).toContain("facebook / cpc");
    expect(text).toContain("Último clique com UTM");
  });

  it("explica migração pendente em vez de mostrar zero", async () => {
    api.getSalesByOrigin.mockResolvedValue({ ok: true, status: "migration_pending", provider: "fbits", totals: null, channels: [], campaigns: [], attribution_model: "last_click_utm", attribution_model_label: "x", period: { start: "", end: "" } });
    await act(async () => root.render(<SalesByOriginPanel />));
    await flush();
    expect(container.textContent).toContain("ainda está sendo ativada");
  });

  it("some quando a empresa não tem loja conectada", async () => {
    api.getSalesByOrigin.mockResolvedValue({ ok: true, status: "not_connected", provider: null, totals: null, channels: [], campaigns: [], attribution_model: "", attribution_model_label: "", period: { start: "", end: "" } });
    await act(async () => root.render(<SalesByOriginPanel />));
    await flush();
    expect(container.querySelector("[data-testid=sales-by-origin]")).toBeNull();
  });
});
